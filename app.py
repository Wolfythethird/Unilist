import streamlit as st
import backend

# --- APPS SETUP ENGINE ---
st.set_page_config(page_title="Universal Wishlist Engine", layout="wide", initial_sidebar_state="expanded")

# Initialize session state
if "logged_in" not in st.session_state: 
    st.session_state.logged_in = False
if "user_id" not in st.session_state: 
    st.session_state.user_id = None
if "username" not in st.session_state: 
    st.session_state.username = None
if "session_token" not in st.session_state: 
    st.session_state.session_token = None
if "invited_accepted" not in st.session_state: 
    st.session_state.invited_accepted = False

# Try to restore session from browser file on app startup
saved_token = backend.get_session_from_browser()
if saved_token and not st.session_state.logged_in:
    session_data = backend.verify_session(saved_token)
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
    user_data = backend.get_user_by_share_uuid(share_uuid)
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
                    if target_share_user_id:
                        backend.add_invitation(target_share_user_id, st.session_state.user_id)
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
                                user_record = backend.get_user_by_username(u_in)
                                if user_record and backend.check_password(p_in, user_record[2]):
                                    session_token = backend.create_session(user_record[0], user_record[1])
                                    st.session_state.logged_in = True
                                    st.session_state.user_id = user_record[0]
                                    st.session_state.username = user_record[1]
                                    st.session_state.session_token = session_token
                                    backend.save_session_to_browser(session_token)
                                    st.success("Signed in! Accepting invitation...")
                                    st.rerun()
                                else: 
                                    st.error("Invalid credentials.")
                    with auth_tab2:
                        with st.form("invite_register_form"):
                            u_reg = st.text_input("Create Username")
                            p_reg = st.text_input("Create Password", type="password")
                            if st.form_submit_button("Register", type="primary"):
                                if u_reg and p_reg:
                                    if backend.register_user(u_reg, p_reg):
                                        user_record = backend.get_user_by_username(u_reg)
                                        session_token = backend.create_session(user_record[0], user_record[1])
                                        st.session_state.logged_in = True
                                        st.session_state.user_id = user_record[0]
                                        st.session_state.username = user_record[1]
                                        st.session_state.session_token = session_token
                                        backend.save_session_to_browser(session_token)
                                        st.success("Account created! Accepting invitation...")
                                        st.rerun()
                                    else: 
                                        st.error("Username already taken.")
    st.stop()

# ROUTE B: Main Shared Application Hub
else:
    with st.sidebar:
        st.title("🎁 Wishlist Engine")
        if st.session_state.logged_in:
            st.success(f"Signed in as: **@{st.session_state.username}**")
            user_share_uuid = backend.get_user_share_uuid(st.session_state.user_id)
            st.caption(f"🔗 Your share link: `?share={user_share_uuid}`")
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
                backend.clear_browser_session()
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
                    user_record = backend.get_user_by_username(u_in)
                    if user_record and backend.check_password(p_in, user_record[2]):
                        session_token = backend.create_session(user_record[0], user_record[1])
                        st.session_state.logged_in = True
                        st.session_state.user_id = user_record[0]
                        st.session_state.username = user_record[1]
                        st.session_state.session_token = session_token
                        backend.save_session_to_browser(session_token)
                        st.rerun()
                    else: 
                        st.error("Invalid credentials provided.")
        with auth_tab2:
            with st.form("register_form"):
                u_reg = st.text_input("Create Username")
                p_reg = st.text_input("Create Password", type="password")
                if st.form_submit_button("Register Account"):
                    if u_reg and p_reg:
                        if backend.register_user(u_reg, p_reg):
                            user_record = backend.get_user_by_username(u_reg)
                            session_token = backend.create_session(user_record[0], user_record[1])
                            st.session_state.logged_in = True
                            st.session_state.user_id = user_record[0]
                            st.session_state.username = user_record[1]
                            st.session_state.session_token = session_token
                            backend.save_session_to_browser(session_token)
                            st.success("Account created and signed in!")
                            st.rerun()
                        else: 
                            st.error("Username already taken.")

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
                    is_valid, fixed_url = backend.validate_and_fix_url(target_url)
                    if not is_valid:
                        st.error("❌ Invalid URL format. Please enter a valid website URL (e.g., amazon.com or https://example.com)")
                    else:
                        try:
                            scraped_data = backend.scrape_product_info(fixed_url, manual_price)
                            backend.add_scraped_item(
                                user_id=st.session_state.user_id,
                                title=scraped_data["title"],
                                url=fixed_url,
                                image_url=scraped_data["image_url"],
                                target_price=scraped_data["target_price"],
                                instructions=instructions
                            )
                            st.success("Item injected into database!")
                        except Exception as e:
                            st.error(f"Scraping Error: {e}")
                else:
                    backend.add_custom_item(st.session_state.user_id, instructions, manual_price)
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

            col_search, col_filter = st.columns(2)
            with col_search:
                search_query = st.text_input("🔍 Search items by title...", "").strip().lower()
            with col_filter:
                filter_status = st.selectbox("📌 Status Filter", ["All Items", "Available", "Claimed / Fully Funded"])

            # --- DYNAMIC BACKGROUND AUTO-RESCRAPE ENGINE ---
            raw_items = backend.get_user_items(active_user_id)
            items_array = []
            
            # Use streamlit session state to prevent infinite reload loop in a single run
            if "rescraped_this_session" not in st.session_state:
                st.session_state.rescraped_this_session = set()
            
            for item in raw_items:
                id, title, url, img, target, pledged, inst, funded, bought = item
                
                # If it has a URL and we haven't scraped it yet in this specific app run
                if url and id not in st.session_state.rescraped_this_session:
                    try:
                        # Attempt an on-the-fly rescrape
                        scraped_data = backend.scrape_product_info(url, target)
                        new_price = scraped_data["target_price"]
                        new_title = scraped_data["title"]
                        
                        # Update DB if data changes (e.g. price drops or hardware is fixed)
                        if float(new_price) != float(target) or new_title != title:
                            backend.update_item_price_and_title(id, new_title, new_price)
                            # Update local reference values for this render cycle
                            target = new_price
                            title = new_title
                        
                        st.session_state.rescraped_this_session.add(id)
                    except Exception as e:
                        # Quietly fall back to previous DB records if scraping fails
                        pass
                
                # Append finalized up-to-date item data structure
                items_array.append((id, title, url, img, target, pledged, inst, funded, bought))

            # --- SEARCH, FILTER & RENDER ENGINE ---
            if not items_array:
                st.info("No items mapped to this user node profile yet.")
            else:
                filtered_items = []
                for node in items_array:
                    id, title, url, img, target, pledged, inst, funded, bought = node
                    
                    if search_query and search_query not in title.lower():
                        continue
                        
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
                                if img and isinstance(img, str) and (img.startswith("http://") or img.startswith("https://")):
                                    st.image(img, use_container_width=True)
                                else:
                                    st.markdown("<h2 style='text-align: center; margin: 30px 0;'>🎁</h2>", unsafe_allow_html=True)
                                
                                if url:
                                    st.markdown(f"#### [{title}]({url})")
                                else:
                                    st.markdown(f"#### {title}")
                                    
                                # --- PROGRESS AND PRICE DISPLAY ---
                                if url and t_val == 0.0:
                                    # It's a scraped item that is free
                                    st.success("🟢 **FREE**")
                                elif t_val > 0.0:
                                    # Paid items
                                    st.write(f"**Target:** ${t_val:,.2f} | **Pledged:** ${p_val:,.2f}")
                                    st.progress(progress_pct)
                                else:
                                    # Custom cash funds without a link
                                    st.write(f"**Direct Contributions:** ${p_val:,.2f}")
                                    
                                st.caption(f"Instruction Protocol: {inst}")
                                
                                if is_owner:
                                    st.markdown("---")
                                    if bought:
                                        st.info("🎁 Marked as Bought by a Guest")
                                    elif funded:
                                        st.success("💰 Cash Target Met!")
                                        
                                    if st.button("🗑️ Remove From List", key=f"del_{id}", use_container_width=True, type="secondary"):
                                        backend.delete_item(id)
                                        st.success("Item Purged!")
                                        st.rerun()
                                else:
                                    if is_claimed:
                                        if bought:
                                            st.error("🔒 Already Purchased")
                                        else:
                                            st.success("🎉 Fully Crowdfunded")
                                    else:
                                        gst_col1, gst_col2 = st.columns(2)
                                        with gst_col1:
                                            with st.popover("💸 Chip in Cash", use_container_width=True):
                                                amt_pledge = st.number_input("Pledge Value ($)", min_value=1.0, step=10.0, key=f"p_{id}")
                                                if st.button("Confirm Cash", key=f"b_{id}", use_container_width=True):
                                                    backend.pledge_money(id, amt_pledge)
                                                    st.rerun()
                                        with gst_col2:
                                            if st.button("🎁 Mark as Bought", key=f"bt_{id}", use_container_width=True, type="primary", help="Select this if you bought the physical item outside this app"):
                                                backend.mark_item_as_bought(id)
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
        
        invited_wishlists = backend.get_invited_wishlists(st.session_state.user_id) if st.session_state.logged_in else []
        
        if not invited_wishlists:
            st.info("📭 You haven't been invited to any wishlists yet. Share your link to invite others!")
        else:
            for user_id, username, share_uuid in invited_wishlists:
                if st.button(f"👤 View @{username}'s Wishlist", key=f"invited_{user_id}"):
                    st.query_params['share'] = share_uuid
                    st.session_state.invited_accepted = True
                    st.rerun()