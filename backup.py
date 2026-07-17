import streamlit as st
import requests
from bs4 import BeautifulSoup
from sqlalchemy import create_engine, text
import bcrypt
import re
from curl_cffi import requests as cffi_requests
import json
import os
from datetime import datetime
import uuid

# --- SESSION MANAGEMENT ---
SESSIONS_FILE = "user_sessions.json"

def load_sessions():
    """Load active user sessions from file"""
    if os.path.exists(SESSIONS_FILE):
        try:
            with open(SESSIONS_FILE, "r") as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_sessions(sessions):
    """Save user sessions to file"""
    with open(SESSIONS_FILE, "w") as f:
        json.dump(sessions, f)

def create_session(user_id, username):
    """Create a new session token for a user"""
    session_token = str(uuid.uuid4())
    sessions = load_sessions()
    sessions[session_token] = {
        "user_id": user_id,
        "username": username,
        "created": datetime.now().isoformat()
    }
    save_sessions(sessions)
    return session_token

def verify_session(session_token):
    """Verify and retrieve user from session token"""
    sessions = load_sessions()
    if session_token in sessions:
        return sessions[session_token]
    return None

def get_session_from_browser():
    """Get saved session ID from browser state"""
    import hashlib
    import socket
    # Create a unique ID based on browser fingerprint
    hostname = socket.gethostname()
    browser_id = hashlib.md5(hostname.encode()).hexdigest()[:16]
    
    session_file = f".session_{browser_id}"
    if os.path.exists(session_file):
        try:
            with open(session_file, "r") as f:
                token = f.read().strip()
                # Verify the token is still valid
                if verify_session(token):
                    return token
                else:
                    os.remove(session_file)
        except:
            pass
    return None

def save_session_to_browser(session_token):
    """Save session token to browser-specific file"""
    import hashlib
    import socket
    hostname = socket.gethostname()
    browser_id = hashlib.md5(hostname.encode()).hexdigest()[:16]
    
    session_file = f".session_{browser_id}"
    with open(session_file, "w") as f:
        f.write(session_token)

def clear_browser_session():
    """Clear the saved session for this browser"""
    import hashlib
    import socket
    hostname = socket.gethostname()
    browser_id = hashlib.md5(hostname.encode()).hexdigest()[:16]
    
    session_file = f".session_{browser_id}"
    if os.path.exists(session_file):
        os.remove(session_file)

# --- CORE DATABASE SETUP (SQLite) ---
DATABASE_URL = "sqlite:///wishlist_v2.db"
engine = create_engine(DATABASE_URL)

# --- SCHEMA ENGINE (Upgraded with Purchase Flags) ---
with engine.connect() as conn:
    # Users Directory Table
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            share_uuid TEXT UNIQUE NOT NULL
        )
    """))
    # Wishlist Items Table
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            url TEXT,
            image_url TEXT,
            target_price DECIMAL(10, 2) DEFAULT 0.00,
            funds_pledged DECIMAL(10, 2) DEFAULT 0.00,
            instructions TEXT,
            is_fully_funded BOOLEAN DEFAULT 0,
            is_bought BOOLEAN DEFAULT 0,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    """))
    # Invitations Table - tracks who invited whom
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS invitations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invited_by_id INTEGER NOT NULL,
            invited_user_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(invited_by_id) REFERENCES users(id),
            FOREIGN KEY(invited_user_id) REFERENCES users(id),
            UNIQUE(invited_by_id, invited_user_id)
        )
    """))
    
    # SYSTEM MIGRATION: Add the 'share_uuid' column if it's missing
    try:
        conn.execute(text("ALTER TABLE users ADD COLUMN share_uuid TEXT UNIQUE"))
        conn.commit()
    except Exception:
        pass
    
    # SYSTEM MIGRATION: Add the 'is_bought' column if it's missing from older database files
    try:
        conn.execute(text("ALTER TABLE items ADD COLUMN is_bought BOOLEAN DEFAULT 0"))
        conn.commit()
    except Exception:
        pass
    conn.commit()

# --- BACKEND LOGIC CORE ---
def ensure_user_has_uuid(user_id):
    """Ensure a user has a share_uuid, generate one if missing"""
    with engine.connect() as conn:
        result = conn.execute(text("SELECT share_uuid FROM users WHERE id = :id"), {"id": user_id})
        row = result.fetchone()
        if row and row[0]:
            return row[0]
        else:
            # Generate and save a UUID
            new_uuid = str(uuid.uuid4())
            conn.execute(text("UPDATE users SET share_uuid = :uuid WHERE id = :id"), {"uuid": new_uuid, "id": user_id})
            conn.commit()
            return new_uuid

def get_user_by_username(username):
    with engine.connect() as conn:
        result = conn.execute(text("SELECT id, username, password_hash FROM users WHERE username = :u"), {"u": username.strip().lower()})
        user_data = result.fetchone()
        if user_data:
            # Ensure the user has a UUID
            ensure_user_has_uuid(user_data[0])
        return user_data

def register_user(username, password):
    hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    share_uuid = str(uuid.uuid4())
    try:
        with engine.connect() as conn:
            conn.execute(text("INSERT INTO users (username, password_hash, share_uuid) VALUES (:u, :p, :uuid)"), {"u": username.strip().lower(), "p": hashed, "uuid": share_uuid})
            conn.commit()
        return True
    except Exception:
        return False

def check_password(password, hashed):
    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))

def get_user_by_share_uuid(share_uuid):
    """Get user by their share UUID"""
    with engine.connect() as conn:
        result = conn.execute(text("SELECT id, username, share_uuid FROM users WHERE share_uuid = :uuid"), {"uuid": share_uuid})
        return result.fetchone()

def get_user_share_uuid(user_id):
    """Get the share UUID for a user"""
    with engine.connect() as conn:
        result = conn.execute(text("SELECT share_uuid FROM users WHERE id = :id"), {"id": user_id})
        row = result.fetchone()
        return row[0] if row else None

def add_invitation(invited_by_id, invited_user_id):
    """Track that user_id was invited by inviter_id"""
    try:
        with engine.connect() as conn:
            conn.execute(text("""
                INSERT OR IGNORE INTO invitations (invited_by_id, invited_user_id) 
                VALUES (:by_id, :user_id)
            """), {"by_id": invited_by_id, "user_id": invited_user_id})
            conn.commit()
        return True
    except Exception:
        return False

def get_invited_wishlists(current_user_id):
    """Get all wishlists this user has been invited to"""
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT DISTINCT u.id, u.username, u.share_uuid
            FROM invitations i
            JOIN users u ON i.invited_by_id = u.id
            WHERE i.invited_user_id = :user_id
        """), {"user_id": current_user_id})
        return result.fetchall()

def validate_and_fix_url(url):
    """Validate and fix URL format. Returns (is_valid, fixed_url)"""
    url = url.strip()
    if not url:
        return False, ""
    
    # Check if URL has a scheme, if not add https://
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    
    # Basic validation - must have a dot in the domain
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        if not parsed.netloc or "." not in parsed.netloc:
            return False, ""
        return True, url
    except Exception:
        return False, ""

def scrape_and_add_item(url, instructions, target_price_manual, user_id):
    try:
        # Validate and fix URL
        is_valid, fixed_url = validate_and_fix_url(url)
        if not is_valid:
            st.error("❌ Invalid URL format. Please enter a valid website URL (e.g., amazon.com or https://example.com)")
            return False
        
        url = fixed_url
        res = cffi_requests.get(url, impersonate="chrome120", timeout=15, headers={"Accept-Language": "en-US,en;q=0.9"})
        if res.status_code != 200:
            st.error(f"Scraper Blocked (Status: {res.status_code}). Try adding manually.")
            return False

        soup = BeautifulSoup(res.text, 'lxml')
        title = None
        for tag, attrs in [("meta", {"property": "og:title"}), ("span", {"id": "productTitle"}), ("h1", {"id": "title"})]:
            found = soup.find(tag, attrs)
            if found:
                title = found["content"] if tag == "meta" else found.text.strip()
                break
        if not title:
            title = soup.title.string.strip() if soup.title else "Amazon Product Node"

        image_url = ""
        for tag, attrs in [("meta", {"property": "og:image"}), ("img", {"id": "landingImage"}), ("img", {"id": "imgBlkFront"})]:
            found = soup.find(tag, attrs)
            if found:
                image_url = found["content"] if tag == "meta" else found.get("src", "")
                break

        target_price = None
        meta_price = soup.find("meta", property="product:price:amount")
        if meta_price and meta_price.get("content"):
            try: target_price = float(meta_price["content"])
            except ValueError: pass

        if not target_price:
            p_whole = soup.find("span", class_="a-price-whole")
            p_frac = soup.find("span", class_="a-price-fraction")
            if p_whole and p_frac:
                target_price = float(f"{re.sub(r'[^\d]', '', p_whole.text)}.{re.sub(r'[^\d]', '', p_frac.text)}")

        if not target_price:
            target_price = float(target_price_manual) if target_price_manual else 0.0

        with engine.connect() as conn:
            conn.execute(text("""
                INSERT INTO items (user_id, title, url, image_url, target_price, instructions, is_bought) 
                VALUES (:uid, :title, :url, :image_url, :target_price, :instructions, 0)
            """), {"uid": user_id, "title": title.strip(), "url": url, "image_url": image_url, "target_price": target_price, "instructions": instructions})
            conn.commit()
        return True
    except Exception as e:
        st.error(f"Scraping Error: {e}")
        return False

def pledge_money(item_id, amount):
    with engine.begin() as conn:
        result = conn.execute(text("SELECT funds_pledged, target_price FROM items WHERE id = :id"), {"id": item_id})
        item = result.fetchone()
        if item:
            new_pledged = float(item[0]) + float(amount)
            target = float(item[1])
            is_funded = 1 if (target > 0 and new_pledged >= target) else 0
            conn.execute(text("UPDATE items SET funds_pledged = :pledged, is_fully_funded = :funded WHERE id = :id"), {"pledged": new_pledged, "funded": is_funded, "id": item_id})

def mark_item_as_bought(item_id):
    with engine.connect() as conn:
        conn.execute(text("UPDATE items SET is_bought = 1, is_fully_funded = 1 WHERE id = :id"), {"id": item_id})
        conn.commit()

def delete_item(item_id):
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM items WHERE id = :id"), {"id": item_id})
        conn.commit()

# --- APPS SETUP ENGINE ---
st.set_page_config(page_title="Universal Wishlist Engine", layout="wide", initial_sidebar_state="expanded")

# Initialize session state
if "logged_in" not in st.session_state: st.session_state.logged_in = False
if "user_id" not in st.session_state: st.session_state.user_id = None
if "username" not in st.session_state: st.session_state.username = None
if "session_token" not in st.session_state: st.session_state.session_token = None
if "invited_accepted" not in st.session_state: st.session_state.invited_accepted = False

# Try to restore session from browser file on app startup
saved_token = get_session_from_browser()
if saved_token and not st.session_state.logged_in:
    session_data = verify_session(saved_token)
    if session_data:
        st.session_state.logged_in = True
        st.session_state.user_id = session_data["user_id"]
        st.session_state.username = session_data["username"]
        st.session_state.session_token = saved_token

url_params = st.query_params
share_uuid = url_params.get("share")

# Resolve share UUID to get target user
target_share_user = None
target_share_user_id = None
if share_uuid:
    user_data = get_user_by_share_uuid(share_uuid)
    if user_data:
        target_share_user = user_data[1]  # username
        target_share_user_id = user_data[0]  # id

# ROUTE A: Discord Invite Interceptor Page Layout
if share_uuid and target_share_user and not st.session_state.invited_accepted:
    st.markdown("<br><br>", unsafe_allow_html=True)
    col_l, col_m, col_r = st.columns(3)
    with col_m:
        with st.container(border=True):
            st.markdown("<p style='text-align: center; color: #5865F2; font-size: 14px; font-weight: bold; text-transform: uppercase;'>You've Been Invited</p>", unsafe_allow_html=True)
            st.markdown(f"<h2 style='text-align: center; margin-top: 0px;'>Access @{target_share_user}'s Wishlist?</h2>", unsafe_allow_html=True)
            
            if st.session_state.logged_in:
                st.info(f"✅ Signed in as **@{st.session_state.username}**")
                accept_btn = st.button("Accept Invitation", use_container_width=True, type="primary")
                if accept_btn:
                    # Track the invitation
                    if target_share_user_id:
                        add_invitation(target_share_user_id, st.session_state.user_id)
                    st.session_state.invited_accepted = True
                    st.rerun()
            else:
                st.warning("🔐 Sign in or register to accept this invitation")
                with st.expander("Sign In / Register", expanded=True):
                    auth_tab1, auth_tab2 = st.tabs(["Sign In", "Register"])
                    with auth_tab1:
                        with st.form("invite_login_form"):
                            u_in = st.text_input("Username")
                            p_in = st.text_input("Password", type="password")
                            if st.form_submit_button("Sign In", type="primary"):
                                user_record = get_user_by_username(u_in)
                                if user_record and check_password(p_in, user_record[2]):
                                    session_token = create_session(user_record[0], user_record[1])
                                    st.session_state.logged_in = True
                                    st.session_state.user_id = user_record[0]
                                    st.session_state.username = user_record[1]
                                    st.session_state.session_token = session_token
                                    # Save session to browser file
                                    save_session_to_browser(session_token)
                                    st.success("Signed in! Accepting invitation...")
                                    st.rerun()
                                else: st.error("Invalid credentials.")
                    with auth_tab2:
                        with st.form("invite_register_form"):
                            u_reg = st.text_input("Create Username")
                            p_reg = st.text_input("Create Password", type="password")
                            if st.form_submit_button("Register", type="primary"):
                                if u_reg and p_reg:
                                    if register_user(u_reg, p_reg):
                                        user_record = get_user_by_username(u_reg)
                                        session_token = create_session(user_record[0], user_record[1])
                                        st.session_state.logged_in = True
                                        st.session_state.user_id = user_record[0]
                                        st.session_state.username = user_record[1]
                                        st.session_state.session_token = session_token
                                        # Save session to browser file
                                        save_session_to_browser(session_token)
                                        st.success("Account created! Accepting invitation...")
                                        st.rerun()
                                    else: st.error("Username already taken.")
    st.stop()

# ROUTE B: Main Shared Application Hub
else:
    with st.sidebar:
        st.title("🎁 Wishlist Engine")
        if st.session_state.logged_in:
            st.success(f"Signed in as: **@{st.session_state.username}**")
            user_share_uuid = get_user_share_uuid(st.session_state.user_id)
            st.caption(f"🔗 Your share link: `?share={user_share_uuid}`")
            # Show different menu options based on whether viewing shared wishlist
            if target_share_user:
                nav_selection = st.radio("Navigation Menu", ["My Wishlist Dashboard", "🌐 Discover Public Wishlists"], index=1)
            else:
                nav_selection = st.radio("Navigation Menu", ["My Wishlist Dashboard", "➕ Add New Item", "🌐 Discover Public Wishlists"])
            st.markdown("<br><br>", unsafe_allow_html=True)
            if st.button("Log Out", use_container_width=True, type="secondary"):
                st.session_state.logged_in = False
                st.session_state.user_id = None
                st.session_state.username = None
                st.session_state.session_token = None
                st.session_state.invited_accepted = False
                st.query_params.clear()
                # Clear session from browser file
                clear_browser_session()
                st.rerun()
        else:
            st.info("💡 Log in or browse public lists.")
            nav_selection = st.radio("Navigation Menu", ["Sign In / Register", "🌐 Discover Public Wishlists"])

    # PAGE 1: AUTHENTICATION ROUTER
    if nav_selection == "Sign In / Register":
        st.subheader("Account Authorization Portal")
        auth_tab1, auth_tab2 = st.tabs(["Existing User Sign-In", "Register New Account"])
        with auth_tab1:
            with st.form("login_form"):
                u_in = st.text_input("Username")
                p_in = st.text_input("Password", type="password")
                if st.form_submit_button("Sign In", type="primary"):
                    user_record = get_user_by_username(u_in)
                    if user_record and check_password(p_in, user_record[2]):
                        session_token = create_session(user_record[0], user_record[1])
                        st.session_state.logged_in = True
                        st.session_state.user_id = user_record[0]
                        st.session_state.username = user_record[1]
                        st.session_state.session_token = session_token
                        # Save session to browser file
                        save_session_to_browser(session_token)
                        st.rerun()
                    else: st.error("Invalid credentials provided.")
        with auth_tab2:
            with st.form("register_form"):
                u_reg = st.text_input("Create Username")
                p_reg = st.text_input("Create Password", type="password")
                if st.form_submit_button("Register Account"):
                    if u_reg and p_reg:
                        if register_user(u_reg, p_reg):
                            user_record = get_user_by_username(u_reg)
                            session_token = create_session(user_record[0], user_record[1])
                            st.session_state.logged_in = True
                            st.session_state.user_id = user_record[0]
                            st.session_state.username = user_record[1]
                            st.session_state.session_token = session_token
                            # Save session to browser file
                            save_session_to_browser(session_token)
                            st.success("Account created and signed in!")
                            st.rerun()
                        else: st.error("Username already taken.")

    # Clear target_share_user when viewing own dashboard
    if nav_selection == "My Wishlist Dashboard" and target_share_user:
        st.query_params.clear()
        st.rerun()

    # PAGE 2: CORE INPUT CONTROLLER
    elif nav_selection == "➕ Add New Item":
        st.subheader("Import Target Item Node")
        with st.form("scraper_input_form", clear_on_submit=True):
            target_url = st.text_input("Pasted Product Source URL (Leave blank for custom cash funds):")
            manual_price = st.number_input("Target Price ($)", min_value=0.0, step=1.0)
            instructions = st.text_area(
                "Giver Payment / Contribution Instructions:", 
                "Venmo me at @username, drop off cash, or click 'Mark as Bought' if buying the physical package!"
            )
            if st.form_submit_button("Scrape & Commit to Database", type="primary"):
                if target_url:
                    if scrape_and_add_item(target_url, instructions, manual_price, st.session_state.user_id):
                        st.success("Item injected into database!")
                else:
                    with engine.connect() as conn:
                        conn.execute(
                            text("INSERT INTO items (user_id, title, instructions, target_price, is_bought) VALUES (:uid, :t, :i, :p, 0)"),
                            {"uid": st.session_state.user_id, "t": "Custom Cash Fund Node", "i": instructions, "p": manual_price}
                        )
                        conn.commit()
                    st.success("Custom cash entity built!")

    # PAGE 3: DASHBOARD VIEWS ENGINE
    elif nav_selection == "My Wishlist Dashboard" or (target_share_user and st.session_state.invited_accepted):
        is_owner = not target_share_user or (target_share_user == st.session_state.username)
        active_username = target_share_user if target_share_user else st.session_state.username
        active_user_id = target_share_user_id if target_share_user_id else st.session_state.user_id

        if not active_user_id:
            st.error("Target user node matching this context path does not exist.")
        else:
            st.title(f"🎁 @{active_username}'s Universal Wishlist")

            # --- SEARCH AND FILTER CONTROLLER BAR ---
            col_search, col_filter = st.columns(2)
            with col_search:
                search_query = st.text_input("🔍 Search items by title...", "").strip().lower()
            with col_filter:
                filter_status = st.selectbox("📌 Status Filter", ["All Items", "Available", "Claimed / Fully Funded"])

            with engine.connect() as conn:
                items_array = conn.execute(
                    text("SELECT id, title, url, image_url, target_price, funds_pledged, instructions, is_fully_funded, is_bought FROM items WHERE user_id = :uid"),
                    {"uid": active_user_id}
                ).fetchall()

            if not items_array:
                st.info("No items mapped to this user node profile yet.")
            else:
                # Process runtime in-memory database filtering
                filtered_items = []
                for node in items_array:
                    id, title, url, img, target, pledged, inst, funded, bought = node
                    
                    # Apply text search parameter matching
                    if search_query and search_query not in title.lower():
                        continue
                        
                    # Apply status query filter matching
                    is_claimed = (funded == 1 or bought == 1 or (float(target) > 0 and float(pledged) >= float(target)))
                    if filter_status == "Available" and is_claimed:
                        continue
                    if filter_status == "Claimed / Fully Funded" and not is_claimed:
                        continue
                        
                    filtered_items.append(node)

                if not filtered_items:
                    st.warning("No wishlist items match your dynamic filter selections.")
                else:
                    grid_cols = st.columns(3)
                    for index, item_node in enumerate(filtered_items):
                        id, title, url, img, target, pledged, inst, funded, bought = item_node
                        
                        t_val = float(target) if target else 0.0
                        p_val = float(pledged) if pledged else 0.0
                        progress_pct = min(p_val / t_val, 1.0) if t_val > 0 else 0.0
                        is_claimed = (funded == 1 or bought == 1 or (t_val > 0 and p_val >= t_val))
                        
                        with grid_cols[index % 3]:
                            with st.container(border=True):
                                # Cleanly validate if 'img' is a legitimate web URL string
                                if img and isinstance(img, str) and (img.startswith("http://") or img.startswith("https://")):
                                    st.image(img, use_container_width=True)
                                else:
                                    # Fallback to a clean package emoji instead of a broken browser block link
                                    st.markdown("<h2 style='text-align: center; margin: 30px 0;'>🎁</h2>", unsafe_allow_html=True)
                                
                                if url:
                                    st.markdown(f"#### [{title}]({url})")
                                else:
                                    st.markdown(f"#### {title}")
                                    
                                if t_val > 0:
                                    st.write(f"**Target:** ${t_val:,.2f} | **Pledged:** ${p_val:,.2f}")
                                    st.progress(progress_pct)
                                else:
                                    st.write(f"**Direct Contributions:** ${p_val:,.2f}")
                                    
                                st.caption(f"Instruction Protocol: {inst}")
                                
                                # --- CONDITIONAL USER ACTION FOOTER INTERFACES ---
                                if is_owner:
                                    # Owner View: Manage Items
                                    st.markdown("---")
                                    if bought:
                                        st.info("🎁 Marked as Bought by a Guest")
                                    elif funded:
                                        st.success("💰 Cash Target Met!")
                                        
                                    if st.button("🗑️ Remove From List", key=f"del_{id}", use_container_width=True, type="secondary"):
                                        delete_item(id)
                                        st.success("Item Purged!")
                                        st.rerun()
                                else:
                                    # Guest View: Claim / Fulfill Items
                                    if is_claimed:
                                        if bought:
                                            st.error("🔒 Already Purchased")
                                        else:
                                            st.success("🎉 Fully Crowdfunded")
                                    else:
                                        # Render split buttons for cash contributions vs standard package buying
                                        gst_col1, gst_col2 = st.columns(2)
                                        with gst_col1:
                                            with st.popover("💸 Chip in Cash", use_container_width=True):
                                                amt_pledge = st.number_input("Pledge Value ($)", min_value=1.0, step=10.0, key=f"p_{id}")
                                                if st.button("Confirm Cash", key=f"b_{id}", use_container_width=True):
                                                    pledge_money(id, amt_pledge)
                                                    st.rerun()
                                        with gst_col2:
                                            if st.button("🎁 Mark as Bought", key=f"bt_{id}", use_container_width=True, type="primary", help="Select this if you bought the physical item outside this app"):
                                                mark_item_as_bought(id)
                                                st.success("Claimed!")
                                                st.rerun()

    # PAGE 4: ENGINE EXPLORER DIRECTORY
    elif nav_selection == "🌐 Discover Public Wishlists":
        st.subheader("Your Invited Wishlists")
        if target_share_user:
            col1, col2 = st.columns([0.9, 0.1])
            with col2:
                if st.button("← Back", use_container_width=True):
                    st.query_params.clear()
                    st.rerun()
        
        # Get wishlists the user has been invited to
        invited_wishlists = get_invited_wishlists(st.session_state.user_id) if st.session_state.logged_in else []
        
        if not invited_wishlists:
            st.info("📭 You haven't been invited to any wishlists yet. Share your link to invite others!")
        else:
            for user_id, username, share_uuid in invited_wishlists:
                if st.button(f"👤 View @{username}'s Wishlist", key=f"invited_{user_id}"):
                    st.query_params['share'] = share_uuid
                    st.session_state.invited_accepted = True
                    st.rerun()
