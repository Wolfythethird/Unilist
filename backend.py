import os
import re
import json
import uuid
import bcrypt
import socket
import hashlib
from datetime import datetime
from sqlalchemy import create_engine, text
from bs4 import BeautifulSoup
from curl_cffi import requests as cffi_requests

# --- SESSIONS FILE CONFIG ---
SESSIONS_FILE = "user_sessions.json"

# --- DATABASE SETUP (SQLite) ---
DATABASE_URL = "sqlite:///wishlist_v2.db"
engine = create_engine(DATABASE_URL)

def init_db():
    """Initialize database schema and perform migrations if necessary"""
    with engine.connect() as conn:
        # Users Table
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                share_uuid TEXT UNIQUE NOT NULL
            )
        """))
        
        # Wishlist Items Table (UPDATED Blueprint)
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
                setting TEXT DEFAULT 'Standard Wish', -- 1. Added directly to fresh schema blueprint
                is_fully_funded BOOLEAN DEFAULT 0,
                is_bought BOOLEAN DEFAULT 0,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        """))
        
        # Invitations Table
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
        
        # Migrations
        try:
            conn.execute(text("ALTER TABLE items ADD COLUMN last_scraped TIMESTAMP DEFAULT CURRENT_TIMESTAMP"))
            conn.commit()
        except Exception:
            pass
        
        try:
            conn.execute(text("ALTER TABLE items ADD COLUMN is_bought BOOLEAN DEFAULT 0"))
            conn.commit()
        except Exception:
            pass

        # 2. Safety Migration step for existing files/environments
        try:
            conn.execute(text("ALTER TABLE items ADD COLUMN setting TEXT DEFAULT 'Standard Wish'"))
            conn.commit()
        except Exception:
            pass
            
        conn.commit()

# Call initialization on import
init_db()

# --- SESSION MANAGEMENT ---
def load_sessions():
    """Load active user sessions from file"""
    if os.path.exists(SESSIONS_FILE):
        try:
            with open(SESSIONS_FILE, "r") as f:
                return json.load(f)
        except Exception:
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

def get_browser_id():
    """Generate a stable browser ID based on hostname"""
    hostname = socket.gethostname()
    return hashlib.md5(hostname.encode()).hexdigest()[:16]

def get_session_from_browser():
    """Get saved session ID from browser state file"""
    browser_id = get_browser_id()
    session_file = f".session_{browser_id}"
    if os.path.exists(session_file):
        try:
            with open(session_file, "r") as f:
                token = f.read().strip()
                if verify_session(token):
                    return token
                else:
                    os.remove(session_file)
        except Exception:
            pass
    return None

def save_session_to_browser(session_token):
    """Save session token to browser-specific file"""
    browser_id = get_browser_id()
    session_file = f".session_{browser_id}"
    with open(session_file, "w") as f:
        f.write(session_token)

def clear_browser_session():
    """Clear the saved session for this browser"""
    browser_id = get_browser_id()
    session_file = f".session_{browser_id}"
    if os.path.exists(session_file):
        os.remove(session_file)

# --- USER MANAGEMENT & DATABASE QUERIES ---
def ensure_user_has_uuid(user_id):
    """Ensure a user has a share_uuid, generate one if missing"""
    with engine.connect() as conn:
        result = conn.execute(text("SELECT share_uuid FROM users WHERE id = :id"), {"id": user_id})
        row = result.fetchone()
        if row and row[0]:
            return row[0]
        else:
            new_uuid = str(uuid.uuid4())
            conn.execute(text("UPDATE users SET share_uuid = :uuid WHERE id = :id"), {"uuid": new_uuid, "id": user_id})
            conn.commit()
            return new_uuid

def get_user_by_username(username):
    with engine.connect() as conn:
        result = conn.execute(text("SELECT id, username, password_hash FROM users WHERE username = :u"), {"u": username.strip().lower()})
        user_data = result.fetchone()
        if user_data:
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
    
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        if not parsed.netloc or "." not in parsed.netloc:
            return False, ""
        return True, url
    except Exception:
        return False, ""

# --- ITEM OPERATIONS ---
def scrape_product_info(url, target_price_manual):
    """Hybrid scraper combining domain-specific rules with universal JSON-LD fallbacks"""
    bypass_cookies = {
        "birthtime": "283993201",
        "wants_mature_content": "1",
        "lastagecheckage": "1-January-1920",
        "mature_content": "1"
    }

    # Custom headers to look like a real browser—crucial for Amazon
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Connection": "keep-alive"
    }

    res = cffi_requests.get(
        url, 
        impersonate="chrome120", 
        timeout=15, 
        headers=headers,
        cookies=bypass_cookies
    )
    
    if res.status_code != 200:
        raise Exception(f"Scraper Blocked (Status: {res.status_code})")

    soup = BeautifulSoup(res.text, 'lxml')
    
    title = None
    target_price = None
    image_url = ""

    # -------------------------------------------------------------------------
    # LAYER 1: DOMAIN SPECIFIC OVERRIDES (Amazon & Steam)
    # -------------------------------------------------------------------------
    url_lower = url.lower()

    if "amazon.com" in url_lower:
        # Check if we got blanked or hit a robot-check screen
        if "captcha" in res.text.lower() or "robot check" in res.text.lower() or not soup.find("span", id="productTitle"):
            # Plan B: Scrape standard metadata elements that Amazon leaves exposed for search spiders
            # FIXED: Wrapped name="title" in an attrs dictionary to avoid BeautifulSoup argument conflicts
            meta_title = soup.find("meta", property="og:title") or soup.find("meta", attrs={"name": "title"})
            if meta_title and meta_title.get("content"):
                title = meta_title["content"].replace("Amazon.com: ", "").strip()
            else:
                title = soup.title.string.replace("Amazon.com", "").strip() if soup.title else "Amazon Product"
            
            # Extract standard image links from metadata paths
            # FIXED: Wrapped name="twitter:image" in an attrs dictionary
            meta_img = soup.find("meta", property="og:image") or soup.find("meta", attrs={"name": "twitter:image"})
            if meta_img:
                image_url = meta_img.get("content", "")
                
            # Scan the entire text profile of the raw page for currency digits using Regex
            # This extracts prices even if Amazon strips out the CSS class wrappers
            price_match = re.search(r'\$[0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{2})', res.text)
            if price_match:
                try:
                    target_price = float(price_match.group(0).replace("$", "").replace(",", ""))
                except ValueError:
                    pass
        else:
            # Plan A: Standard selector extraction if the request successfully bypassed protection
            title_el = soup.find("span", id="productTitle") or soup.find("h1", id="title")
            if title_el:
                title = title_el.text.strip()
            
            img_el = soup.find("img", id="landingImage") or soup.find("img", id="imgBlkFront")
            if img_el:
                image_url = img_el.get("src", "")
                
            p_whole = soup.find("span", class_="a-price-whole")
            p_frac = soup.find("span", class_="a-price-fraction")
            if p_whole and p_frac:
                try:
                    target_price = float(f"{re.sub(r'[^\d]', '', p_whole.text)}.{re.sub(r'[^\d]', '', p_frac.text)}")
                except ValueError:
                    pass

    elif "steampowered.com" in url_lower:
        # Steam Title (prioritize the real app hub header element over meta dates)
        title_el = soup.find("div", class_="apphub_AppName") or soup.find("h1")
        if title_el:
            title = title_el.text.strip()
            
        # Steam Price (Handles Hardware, Accessories, Games, and Sales)
        steam_price_el = soup.select_one(".valvesale_final_price, .discount_final_price, .game_purchase_price, .price, .purchase_price")
        if steam_price_el:
            raw_price = steam_price_el.text.strip().lower()
            if "free" in raw_price:
                target_price = 0.0
            else:
                cleaned_price = re.sub(r'[^\d.]', '', raw_price)
                if cleaned_price:
                    try: target_price = float(cleaned_price)
                    except ValueError: pass

    # -------------------------------------------------------------------------
    # LAYER 2: UNIVERSAL LD-JSON TRACK (For GOG and general sites)
    # -------------------------------------------------------------------------
    if not title or target_price is None:
        schema_scripts = soup.find_all("script", type="application/ld+json")
        for script in schema_scripts:
            try:
                if not script.string: continue
                data = json.loads(script.string.strip())
                
                if isinstance(data, dict) and "@graph" in data:
                    data = data["@graph"]
                if isinstance(data, list):
                    product_node = next((item for item in data if item.get("@type") == "Product"), None)
                    if product_node: data = product_node

                if isinstance(data, dict) and (data.get("@type") == "Product" or "offers" in data):
                    if not title and data.get("name"):
                        title = data.get("name")
                    if not image_url and "image" in data:
                        img_data = data["image"]
                        image_url = img_data[0] if isinstance(img_data, list) else img_data
                    
                    if target_price is None and "offers" in data:
                        offers = data["offers"]
                        if isinstance(offers, list): offers = offers[0]
                        if isinstance(offers, dict):
                            raw_price = offers.get("price")
                            if raw_price is not None:
                                target_price = float(raw_price)
            except Exception:
                continue

    # -------------------------------------------------------------------------
    # LAYER 3: LAST RESORT GLOBAL FALLBACKS
    # -------------------------------------------------------------------------
    if not title:
        title = soup.title.string.strip() if soup.title else "Product Link Node"
    if not image_url:
        og_img = soup.find("meta", property="og:image")
        if og_img: image_url = og_img.get("content", "")

    if target_price is None:
        # FIXED: Wrapped itemprop="price" in an attrs dictionary to stay clean and uniform
        meta_price = soup.find("meta", property="product:price:amount") or soup.find("meta", attrs={"itemprop": "price"})
        if meta_price and meta_price.get("content"):
            try: target_price = float(meta_price["content"])
            except ValueError: pass

    if target_price is None:
        target_price = float(target_price_manual) if target_price_manual else 0.0

    return {
        "title": str(title).strip(),
        "image_url": str(image_url).strip(),
        "target_price": target_price
    }

def add_scraped_item(user_id, title, url, image_url, target_price, instructions, setting="Standard Wish"):
    with engine.connect() as conn:
        conn.execute(text("""
            INSERT INTO items (user_id, title, url, image_url, target_price, instructions, setting, is_bought) 
            VALUES (:uid, :title, :url, :image_url, :target_price, :instructions, :setting, 0)
        """), {
            "uid": user_id, 
            "title": title, 
            "url": url, 
            "image_url": image_url, 
            "target_price": target_price, 
            "instructions": instructions,
            "setting": setting  # <--- Binds the drop-down string value to your database column
        })
        conn.commit()

def add_custom_item(user_id, instructions, target_price):
    with engine.connect() as conn:
        conn.execute(text("""
            INSERT INTO items (user_id, title, instructions, target_price, is_bought) 
            VALUES (:uid, 'Custom Cash Fund Node', :instructions, :target_price, 0)
        """), {
            "uid": user_id, 
            "instructions": instructions, 
            "target_price": target_price
        })
        conn.commit()

def get_user_items(user_id):
    """Fetches user items with explicitly ordered positions for the UI unpack loop"""
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT 
                id, 
                title, 
                url, 
                image_url, 
                target_price, 
                funds_pledged, 
                instructions, 
                is_fully_funded, 
                is_bought,
                setting
            FROM items 
            WHERE user_id = :uid
        """), {"uid": user_id})
        
        # Returns clean, predictably ordered row tuples regardless of schema changes
        return result.fetchall()

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

def update_item_price_and_title(item_id, title, target_price):
    """Updates the price, title, and timestamp of an existing entry"""
    with engine.connect() as conn:
        conn.execute(text("""
            UPDATE items 
            SET title = :title, target_price = :target_price, last_scraped = CURRENT_TIMESTAMP 
            WHERE id = :id
        """), {"title": title, "target_price": target_price, "id": item_id})
        conn.commit()