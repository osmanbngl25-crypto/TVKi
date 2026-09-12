import os
import requests
from supabase import Client, create_client
import streamlit as st

st.set_page_config(
    page_title="TVKi",
    page_icon="logo.png",  # İşte burası hem tarayıcı sekmesinde hem de telefonda ana ekrana ekleyince logonun çıkmasını sağlar
    layout="centered"
)

st.markdown(
    """
    <style>
    .stApp { background-color: #121212; color: #e0e0e0; }
    h1, h2, h3 { color: #ffffff !important; }
    .stTextInput input { background-color: #1e1e1e; color: white; border-radius: 8px; }
    </style>
""",
    unsafe_allow_html=True,
)

# Hassas bilgiler sadece .env dosyasından veya ortam değişkenlerinden çekilir, yedek tutulmaz
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
TMDB_API_KEY = os.getenv("TMDB_API_KEY")

@st.cache_resource
def get_supabase_client():
    try:
        return create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception:
        return None

supabase = get_supabase_client()

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "username" not in st.session_state:
    st.session_state.username = ""
if "search_query_override" not in st.session_state:
    st.session_state.search_query_override = ""

if "username" in st.query_params and not st.session_state.logged_in:
    st.session_state.logged_in = True
    st.session_state.username = st.query_params["username"]

if st.session_state.logged_in:
    st.query_params["username"] = st.session_state.username
else:
    if "username" in st.query_params:
        del st.query_params["username"]

# --- GİRİŞ / KAYIT Ekranı ---
if not st.session_state.logged_in:
    st.title("TVKi")
    st.write("Sosyal film platformuna hoş geldin!")

    if supabase is None:
        st.error("⚠️ Sunucu bağlantısı kurulamadı. İnternet adresini (DNS) kontrol etmeni öneririm.")

    secim = st.radio(
        "İşlem Türü:", ["Giriş Yap", "Kayıt Ol"], key="auth_radio"
    )
    k_adi = st.text_input("Kullanıcı Adı").strip()
    sifre = st.text_input("Şifre", type="password")

    if st.button("Devam Et", use_container_width=True):
        if supabase is None:
            st.error("Veritabanı bağlantısı yok.")
        elif not k_adi or not sifre:
            st.warning("Kullanıcı adı ve şifre boş bırakılamaz!")
        else:
            if secim == "Kayıt Ol":
                try:
                    ex = (
                        supabase.table("users")
                        .select("*")
                        .eq("username", k_adi)
                        .execute()
                    )
                    if ex.data:
                        st.error("Bu kullanıcı adı zaten alınmış.")
                    else:
                        supabase.table("users").insert(
                            {"username": k_adi, "password": sifre}
                        ).execute()
                        st.success("Kayıt başarılı! Giriş yapabilirsin.")
                except Exception as e:
                    st.error(f"Kayıt hatası: {e}")
            else:
                try:
                    res = (
                        supabase.table("users")
                        .select("*")
                        .eq("username", k_adi)
                        .eq("password", sifre)
                        .execute()
                    )
                    if res.data:
                        st.session_state.logged_in = True
                        st.session_state.username = k_adi
                        st.query_params["username"] = k_adi
                        st.rerun()
                    else:
                        st.error("Kullanıcı adı veya şifre hatalı!")
                except Exception as e:
                    st.error(f"Giriş hatası: {e}")
    st.stop()


# --- YARDIMCI FONKSİYONLAR ---
def get_user_lists(uname, l_type):
    if not supabase: return []
    try:
        res = (
            supabase.table("user_lists")
            .select("title, media_type, poster")
            .eq("username", uname)
            .eq("list_type", l_type)
            .execute()
        )
        return res.data
    except:
        return []


def get_user_profile(uname):
    if not supabase: return {"username": uname, "full_name": "", "avatar_url": ""}
    try:
        res = (
            supabase.table("users")
            .select("username, full_name, avatar_url")
            .eq("username", uname)
            .execute()
        )
        if res.data:
            return res.data[0]
    except:
        pass
    return {"username": uname, "full_name": "", "avatar_url": ""}


def get_accepted_friends(uname):
    if not supabase: return []
    try:
        res = (
            supabase.table("follows")
            .select("following")
            .eq("follower", uname)
            .eq("status", "accepted")
            .execute()
            .data
        )
        return [f["following"] for f in res]
    except:
        return []


def send_media_to_chat(receiver, media_title, media_type):
    if not supabase: return
    try:
        msg = f"🎬 Seninle bir yapım paylaştı: **{media_title}** ({media_type})"
        supabase.table("chats").insert({
            "sender": st.session_state.username,
            "receiver": receiver,
            "message": msg,
        }).execute()
        st.success(f"@{receiver} kişisine sohbet üzerinden gönderildi!")
    except Exception as e:
        st.error(f"Gönderilemedi: {e}")


def get_movie_cast_detailed(media_id, tmdb_type):
    try:
        url = f"https://api.themoviedb.org/3/{tmdb_type}/{media_id}/credits?api_key={TMDB_API_KEY}&language=tr-TR"
        res = requests.get(url, timeout=5).json()
        cast = res.get("cast", [])
        actors = []
        for actor in cast:
            name = actor.get("name")
            actor_id = actor.get("id")
            profile_path = actor.get("profile_path")
            profile_url = f"https://image.tmdb.org/t/p/w200{profile_path}" if profile_path else None
            actors.append({"id": actor_id, "name": name, "poster": profile_url})
        return actors
    except:
        return []


def get_actor_filmography(actor_id):
    try:
        url = f"https://api.themoviedb.org/3/person/{actor_id}/combined_credits?api_key={TMDB_API_KEY}&language=tr-TR"
        res = requests.get(url, timeout=5).json()
        cast_list = res.get("cast", [])
        
        valid_media = []
        for item in cast_list:
            m_type = item.get("media_type")
            if m_type not in ["movie", "tv"]:
                continue
            
            title = item.get("title") if m_type == "movie" else item.get("name")
            date_str = item.get("release_date") if m_type == "movie" else item.get("first_air_date")
            year = date_str[:4] if date_str and len(date_str) >= 4 else "0000"
            poster_path = item.get("poster_path")
            poster_url = f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else None
            
            valid_media.append({
                "id": item.get("id"),
                "title": f"{title} ({year})" if year != "0000" else title,
                "year": year,
                "type": "Film" if m_type == "movie" else "Dizi",
                "poster": poster_url
            })
            
        valid_media.sort(key=lambda x: x["year"], reverse=True)
        return valid_media
    except:
        return []


def add_to_list(l_type, m_data):
    if not supabase: return
    try:
        chk = (
            supabase.table("user_lists")
            .select("*")
            .eq("username", st.session_state.username)
            .eq("list_type", l_type)
            .eq("title", m_data["title"])
            .execute()
        )
        if not chk.data:
            supabase.table("user_lists").insert({
                "username": st.session_state.username,
                "list_type": l_type,
                "title": m_data["title"],
                "media_type": m_data["type"],
                "poster": m_data["poster"],
            }).execute()
    except Exception as e:
        st.error(f"Hata: {e}")


def remove_from_list(l_type, title):
    if not supabase: return
    try:
        supabase.table("user_lists").delete().eq(
            "username", st.session_state.username
        ).eq("list_type", l_type).eq("title", title).execute()
    except Exception as e:
        st.error(f"Hata: {e}")


current_user_profile = get_user_profile(st.session_state.username)
c_name = current_user_profile.get("full_name") or st.session_state.username
c_avatar = current_user_profile.get("avatar_url")

# --- ÜST BAR ---
top_col1, top_col2 = st.columns([8, 2])
with top_col1:
    cols_h = st.columns([1, 10])
    with cols_h[0]:
        try:
            st.image("logo.png", width=45)
        except:
            if c_avatar:
                st.image(c_avatar, width=45)
            else:
                st.markdown("🎬")
    with cols_h[1]:
        st.markdown(f"### {c_name} (@{st.session_state.username}) | TVKi")

with top_col2:
    if st.button("Çıkış Yap", use_container_width=True):
        st.session_state.logged_in = False
        st.session_state.username = ""
        if "username" in st.query_params:
            del st.query_params["username"]
        st.rerun()

st.divider()

# --- SEKMELER ---
(
    tab_ana,
    tab_fav,
    tab_watch,
    tab_watched,
    tab_profil,
    tab_ara,
    tab_istek,
    tab_arkadas,
    tab_sohbet,
) = st.tabs([
    "🏠 Ana Sayfa",
    "❤️ Favoriler",
    "📌 İzlenecek",
    "✅ İzlenen",
    "👤 Profil",
    "🔍 Kullanıcı Ara",
    "📩 İstekler",
    "👥 Arkadaşlar",
    "💬 Sohbet",
])


# 1. ANA SAYFA / ARAMA
with tab_ana:
    if st.session_state.search_query_override:
        st.session_state.ana_media_type = "Oyuncu"
        st.session_state.ana_search_actor = st.session_state.search_query_override
        override_val = st.session_state.search_query_override
        st.session_state.search_query_override = ""
    else:
        override_val = ""

    media_type = st.selectbox(
        "Kategori Seç", ["Film", "Dizi", "Oyuncu"], key="ana_media_type"
    )

    friends_list = get_accepted_friends(st.session_state.username)

    if media_type == "Oyuncu":
        search_query = st.text_input(
            "🔍 Oyuncu adı arat...",
            placeholder="Örn: Adam Sandler, Leonardo DiCaprio...",
            key="ana_search_actor",
        )
        if search_query:
            try:
                url = f"https://api.themoviedb.org/3/search/person?api_key={TMDB_API_KEY}&language=tr-TR&query={search_query}"
                res = requests.get(url, timeout=5).json().get("results", [])

                if res:
                    st.success(f"{len(res)} oyuncu bulundu:")
                    for index, item in enumerate(res):
                        name = item.get("name")
                        actor_id = item.get("id")
                        profile_path = item.get("profile_path")
                        poster_url = (
                            f"https://image.tmdb.org/t/p/w500{profile_path}"
                            if profile_path
                            else None
                        )

                        st.subheader(name)
                        if poster_url:
                            st.image(poster_url, width=150)
                        
                        m_data = {
                            "title": name,
                            "type": "Oyuncu",
                            "poster": poster_url,
                        }

                        col_act1, col_act2 = st.columns([2, 8])
                        with col_act1:
                            if st.button("❤️ Favori", key=f"f_actor_{index}"):
                                add_to_list("favorites", m_data)
                                st.success("Oyuncu favorilere eklendi!")

                        st.markdown("#### Oynadığı Yapımlar (Kronolojik)")
                        filmography = get_actor_filmography(actor_id)
                        
                        movies_list = [f for f in filmography if f["type"] == "Film"]
                        shows_list = [f for f in filmography if f["type"] == "Dizi"]

                        with st.expander("🎬 Oynadığı Filmler"):
                            if movies_list:
                                for m_idx, mov in enumerate(movies_list):
                                    col_m_img, col_m_txt, col_m_act = st.columns([1, 4, 3])
                                    with col_m_img:
                                        if mov["poster"]:
                                            st.image(mov["poster"], width=60)
                                    with col_m_txt:
                                        st.write(f"**{mov['title']}**")
                                    with col_m_act:
                                        with st.popover("📤 Paylaş", use_container_width=True):
                                            st.write("Kime gönderilsin?")
                                            if friends_list:
                                                target_f = st.selectbox("Arkadaş", friends_list, key=f"shr_mov_{actor_id}_{m_idx}")
                                                if st.button("Sohbete Gönder", key=f"btn_shr_mov_{actor_id}_{m_idx}"):
                                                    send_media_to_chat(target_f, mov['title'], "Film")
                                            else:
                                                st.warning("Henüz arkadaşın yok.")
                            else:
                                st.info("Film bulunamadı.")

                        with st.expander("📺 Oynadığı Diziler"):
                            if shows_list:
                                for s_idx, show in enumerate(shows_list):
                                    col_s_img, col_s_txt, col_s_act = st.columns([1, 4, 3])
                                    with col_s_img:
                                        if show["poster"]:
                                            st.image(show["poster"], width=60)
                                    with col_s_txt:
                                        st.write(f"**{show['title']}**")
                                    with col_s_act:
                                        with st.popover("📤 Paylaş", use_container_width=True):
                                            st.write("Kime gönderilsin?")
                                            if friends_list:
                                                target_f = st.selectbox("Arkadaş", friends_list, key=f"shr_sho_{actor_id}_{s_idx}")
                                                if st.button("Sohbete Gönder", key=f"btn_shr_sho_{actor_id}_{s_idx}"):
                                                    send_media_to_chat(target_f, show['title'], "Dizi")
                                            else:
                                                st.warning("Henüz arkadaşın yok.")
                            else:
                                st.info("Dizi bulunamadı.")

                        st.divider()
                else:
                    st.warning("Oyuncu bulunamadı.")
            except Exception:
                st.error("Oyuncu araması yapılırken bağlantı kurulamadı.")
    else:
        tmdb_type = "movie" if media_type == "Film" else "tv"
        search_query = st.text_input(
            "🔍 Film veya dizi adı arat...",
            placeholder="Örn: Interstellar, Spider-Man...",
            key="ana_search",
        )

        if search_query:
            try:
                url = f"https://api.themoviedb.org/3/search/{tmdb_type}?api_key={TMDB_API_KEY}&language=tr-TR&query={search_query}"
                res = requests.get(url, timeout=5).json().get("results", [])

                if res:
                    st.success(f"{len(res)} sonuç bulundu:")
                    for index, item in enumerate(res):
                        media_id = item.get("id")
                        title = item.get("title") if tmdb_type == "movie" else item.get("name")
                        overview = item.get("overview")
                        poster_path = item.get("poster_path")
                        date_str = (
                            item.get("release_date", "Bilinmiyor")
                            if tmdb_type == "movie"
                            else item.get("first_air_date", "Bilinmiyor")
                        )
                        year = f" ({date_str[:4]})" if len(date_str) >= 4 else ""
                        full_media_title = f"{title}{year}"

                        st.subheader(full_media_title)
                        poster_url = (
                            f"https://image.tmdb.org/t/p/w500{poster_path}"
                            if poster_path
                            else None
                        )
                        if poster_url:
                            st.image(poster_url, width=150)
                        
                        st.write(overview if overview else "Özet bulunmuyor.")

                        m_data = {
                            "title": full_media_title,
                            "type": media_type,
                            "poster": poster_url,
                        }

                        col1, col2, col3, col4, col5 = st.columns(5)
                        with col1:
                            if st.button("❤️ Favori", key=f"f_{index}"):
                                add_to_list("favorites", m_data)
                                st.success("Favorilere eklendi!")
                        with col2:
                            if st.button("📌 İzle", key=f"w_{index}"):
                                add_to_list("watchlist", m_data)
                                st.success("İzleneceklere eklendi!")
                        with col3:
                            if st.button("✅ İzledim", key=f"wd_{index}"):
                                add_to_list("watched", m_data)
                                st.success("İzlenenlere eklendi!")
                        with col4:
                            with st.popover("📤 Paylaş", use_container_width=True):
                                st.write("Kime gönderilsin?")
                                if friends_list:
                                    target_f = st.selectbox("Arkadaş", friends_list, key=f"share_sel_media_{index}")
                                    if st.button("Sohbete Gönder", key=f"share_btn_media_{index}"):
                                        send_media_to_chat(target_f, full_media_title, media_type)
                                else:
                                    st.warning("Henüz arkadaşın yok.")
                        with col5:
                            if st.button("🎭 Oyuncular", key=f"cast_btn_{index}"):
                                st.session_state[f"show_cast_{index}"] = not st.session_state.get(f"show_cast_{index}", False)

                        if st.session_state.get(f"show_cast_{index}", False):
                            st.markdown("#### Tüm Oyuncular")
                            actors = get_movie_cast_detailed(media_id, tmdb_type)
                            if actors:
                                for a_idx, actor in enumerate(actors):
                                    c_img, c_name_col, c_comp_col = st.columns([1, 5, 2])
                                    with c_img:
                                        if actor["poster"]:
                                            st.image(actor["poster"], width=60)
                                    with c_name_col:
                                        st.write(f"**{actor['name']}**")
                                    with c_comp_col:
                                        if st.button("🧭", key=f"compass_{media_id}_{actor['id']}_{a_idx}" ):
                                            st.session_state.search_query_override = actor['name']
                                            st.rerun()
                            else:
                                st.info("Oyuncu bilgisi bulunamadı.")

                        st.divider()
                else:
                    st.warning("Sonuç bulunamadı.")
            except Exception:
                st.error("Film araması yapılırken bağlantı kurulamadı.")


# 2. FAVORİLERİM
with tab_fav:
    st.title("Favorilerim")
    items = get_user_lists(st.session_state.username, "favorites")
    friends_list = get_accepted_friends(st.session_state.username)
    
    fav_movies = [i for i in items if i["media_type"] == "Film"]
    fav_shows = [i for i in items if i["media_type"] == "Dizi"]
    fav_actors = [i for i in items if i["media_type"] == "Oyuncu"]

    st.subheader("🎬 Filmler")
    if fav_movies:
        for item in fav_movies:
            st.write(f"⭐ **{item['title']}**")
            if item.get("poster"):
                st.image(item["poster"], width=100)
            col_f_act1, col_f_act2 = st.columns(2)
            with col_f_act1:
                if st.button("Listeden Kaldır", key=f"rem_fav_mov_{item['title']}"):
                    remove_from_list("favorites", item["title"])
                    st.rerun()
            with col_f_act2:
                with st.popover("Paylaş"):
                    st.write("Kime gönderilsin?")
                    if friends_list:
                        tf = st.selectbox("Arkadaş", friends_list, key=f"p_fav_mov_{item['title']}")
                        if st.button("Gönder", key=f"btn_p_fav_mov_{item['title']}"):
                            send_media_to_chat(tf, item['title'], "Film")
                    else:
                        st.warning("Arkadaşın yok.")
    else:
        st.info("Favori film bulunmuyor.")

    st.divider()

    st.subheader("📺 Diziler")
    if fav_shows:
        for item in fav_shows:
            st.write(f"⭐ **{item['title']}**")
            if item.get("poster"):
                st.image(item["poster"], width=100)
            col_s_act1, col_s_act2 = st.columns(2)
            with col_s_act1:
                if st.button("Listeden Kaldır", key=f"rem_fav_sho_{item['title']}"):
                    remove_from_list("favorites", item["title"])
                    st.rerun()
            with col_s_act2:
                with st.popover("Paylaş"):
                    st.write("Kime gönderilsin?")
                    if friends_list:
                        tf = st.selectbox("Arkadaş", friends_list, key=f"p_fav_sho_{item['title']}")
                        if st.button("Gönder", key=f"btn_p_fav_sho_{item['title']}"):
                            send_media_to_chat(tf, item['title'], "Dizi")
                    else:
                        st.warning("Arkadaşın yok.")
    else:
        st.info("Favori dizi bulunmuyor.")

    st.divider()

    st.subheader("🎭 Favori Oyuncular")
    if fav_actors:
        for item in fav_actors:
            st.write(f"⭐ **{item['title']}**")
            if item.get("poster"):
                st.image(item["poster"], width=100)
            col_a_act1, col_a_act2 = st.columns(2)
            with col_a_act1:
                if st.button("Listeden Kaldır", key=f"rem_fav_act_{item['title']}"):
                    remove_from_list("favorites", item["title"])
                    st.rerun()
            with col_a_act2:
                with st.popover("Paylaş"):
                    st.write("Kime gönderilsin?")
                    if friends_list:
                        tf = st.selectbox("Arkadaş", friends_list, key=f"p_fav_act_{item['title']}")
                        if st.button("Gönder", key=f"btn_p_fav_act_{item['title']}"):
                            send_media_to_chat(tf, item['title'], "Oyuncu")
                    else:
                        st.warning("Arkadaşın yok.")
    else:
        st.info("Favori oyuncu bulunmuyor.")


# 3. İZLEYECEKLERİM
with tab_watch:
    st.title("İzleyecekler Listen")
    items = get_user_lists(st.session_state.username, "watchlist")
    friends_list = get_accepted_friends(st.session_state.username)
    
    w_movies = [i for i in items if i["media_type"] == "Film"]
    w_shows = [i for i in items if i["media_type"] == "Dizi"]

    st.subheader("🎬 Filmler")
    if w_movies:
        for item in w_movies:
            st.write(f"📌 **{item['title']}**")
            if item.get("poster"):
                st.image(item["poster"], width=100)
            c1, c2 = st.columns(2)
            with c1:
                if st.button("Listeden Kaldır", key=f"rem_wat_mov_{item['title']}"):
                    remove_from_list("watchlist", item["title"])
                    st.rerun()
            with c2:
                with st.popover("Paylaş"):
                    st.write("Kime gönderilsin?")
                    if friends_list:
                        tf = st.selectbox("Arkadaş", friends_list, key=f"p_wat_mov_{item['title']}")
                        if st.button("Gönder", key=f"btn_p_wat_mov_{item['title']}"):
                            send_media_to_chat(tf, item['title'], "Film")
                    else:
                        st.warning("Arkadaşın yok.")
    else:
        st.info("İzlenecek film bulunmuyor.")

    st.divider()

    st.subheader("📺 Diziler")
    if w_shows:
        for item in w_shows:
            st.write(f"📌 **{item['title']}**")
            if item.get("poster"):
                st.image(item["poster"], width=100)
            c1, c2 = st.columns(2)
            with c1:
                if st.button("Listeden Kaldır", key=f"rem_wat_sho_{item['title']}"):
                    remove_from_list("watchlist", item["title"])
                    st.rerun()
            with c2:
                with st.popover("Paylaş"):
                    st.write("Kime gönderilsin?")
                    if friends_list:
                        tf = st.selectbox("Arkadaş", friends_list, key=f"p_wat_sho_{item['title']}")
                        if st.button("Gönder", key=f"btn_p_wat_sho_{item['title']}"):
                            send_media_to_chat(tf, item['title'], "Dizi")
                    else:
                        st.warning("Arkadaşın yok.")
    else:
        st.info("İzlenecek dizi bulunmuyor.")


# 4. İZLEDİKLERİM
with tab_watched:
    st.title("İzlediklerim")
    items = get_user_lists(st.session_state.username, "watched")
    friends_list = get_accepted_friends(st.session_state.username)
    
    wd_movies = [i for i in items if i["media_type"] == "Film"]
    wd_shows = [i for i in items if i["media_type"] == "Dizi"]

    st.subheader("🎬 Filmler")
    if wd_movies:
        for item in wd_movies:
            st.write(f"✅ **{item['title']}**")
            if item.get("poster"):
                st.image(item["poster"], width=100)
            c1, c2 = st.columns(2)
            with c1:
                if st.button("Listeden Kaldır", key=f"rem_wed_mov_{item['title']}"):
                    remove_from_list("watched", item["title"])
                    st.rerun()
            with c2:
                with st.popover("Paylaş"):
                    st.write("Kime gönderilsin?")
                    if friends_list:
                        tf = st.selectbox("Arkadaş", friends_list, key=f"p_wed_mov_{item['title']}")
                        if st.button("Gönder", key=f"btn_p_wed_mov_{item['title']}"):
                            send_media_to_chat(tf, item['title'], "Film")
                    else:
                        st.warning("Arkadaşın yok.")
    else:
        st.info("İzlenen film bulunmuyor.")

    st.divider()

    st.subheader("📺 Diziler")
    if wd_shows:
        for item in wd_shows:
            st.write(f"✅ **{item['title']}**")
            if item.get("poster"):
                st.image(item["poster"], width=100)
            c1, c2 = st.columns(2)
            with c1:
                if st.button("Listeden Kaldır", key=f"rem_wed_sho_{item['title']}"):
                    remove_from_list("watched", item["title"])
                    st.rerun()
            with c2:
                with st.popover("Paylaş"):
                    st.write("Kime gönderilsin?")
                    if friends_list:
                        tf = st.selectbox("Arkadaş", friends_list, key=f"p_wed_sho_{item['title']}")
                        if st.button("Gönder", key=f"btn_p_wed_sho_{item['title']}"):
                            send_media_to_chat(tf, item['title'], "Dizi")
                    else:
                        st.warning("Arkadaşın yok.")
    else:
        st.info("İzlenen dizi bulunmuyor.")


# 5. PROFİL & AYARLAR
with tab_profil:
    st.title("Profil Ayarları")
    user_info = get_user_profile(st.session_state.username)

    new_name = st.text_input(
        "Ad Soyad / Görünen Ad",
        value=user_info.get("full_name") or "",
        key="prof_name",
    )
    new_avatar = st.text_input(
        "Profil Fotoğrafı URL",
        value=user_info.get("avatar_url") or "",
        key="prof_avatar",
    )

    if new_avatar:
        st.write("Önizleme:")
        st.image(new_avatar, width=100)

    if st.button("Profili Güncelle"):
        if supabase:
            supabase.table("users").update(
                {"full_name": new_name, "avatar_url": new_avatar}
            ).eq("username", st.session_state.username).execute()
            st.success("Profil güncellendi!")
            st.rerun()

    followers = []
    following = []
    if supabase:
        try:
            followers = (
                supabase.table("follows")
                .select("*")
                .eq("following", st.session_state.username)
                .eq("status", "accepted")
                .execute()
                .data
            )
            following = (
                supabase.table("follows")
                .select("*")
                .eq("follower", st.session_state.username)
                .eq("status", "accepted")
                .execute()
                .data
            )
        except:
            pass
    st.write(f"👥 Takipçi: **{len(followers)}** | Takip Edilen: **{len(following)}**")

    st.divider()
    st.error("⚠️ Tehlike Bölgesi")
    if st.button("Profili Kalıcı Olarak Sil"):
        if supabase:
            supabase.table("users").delete().eq(
                "username", st.session_state.username
            ).execute()
            st.session_state.logged_in = False
            st.session_state.username = ""
            if "username" in st.query_params:
                del st.query_params["username"]
            st.success("Profil ve tüm verilerin silindi.")
            st.rerun()


# 6. KULLANICI ARA
with tab_ara:
    st.title("Kullanıcı Ara")
    search_u = st.text_input(
        "Kullanıcı adını yaz ve ara (örn: @kullaniciadi):", key="search_user_box"
    )
    if search_u and supabase:
        clean_search = search_u.strip().lstrip("@")

        if clean_search.lower() == st.session_state.username.lower():
            st.info("Bu Hesap Senin!")
        else:
            try:
                res = (
                    supabase.table("users")
                    .select("username, full_name, avatar_url")
                    .ilike("username", f"%{clean_search}%")
                    .neq("username", st.session_state.username)
                    .execute()
                    .data
                )
                if res:
                    for u in res:
                        col_u1, col_u2 = st.columns([1, 8])
                        with col_u1:
                            if u.get("avatar_url"):
                                st.image(u["avatar_url"], width=50)
                            else:
                                st.markdown("👤")
                        with col_u2:
                            display_name = u.get("full_name") or u["username"]
                            st.write(f"**{display_name}** (@{u['username']})")

                            existing_f = (
                                supabase.table("follows")
                                .select("*")
                                .eq("follower", st.session_state.username)
                                .eq("following", u["username"])
                                .execute()
                                .data
                            )
                            if not existing_f:
                                if st.button(
                                    f"Takip İsteği Gönder", key=f"req_{u['username']}"
                                ):
                                    supabase.table("follows").insert({
                                        "follower": st.session_state.username,
                                        "following": u["username"],
                                        "status": "pending",
                                    }).execute()
                                    st.success("İstek gönderildi!")
                                    st.rerun()
                            else:
                                st.info(f"Durum: {existing_f[0]['status']}")
                        st.divider()
                else:
                    st.warning("Kullanıcı bulunamadı.")
            except:
                st.warning("Arama sırasında hata oluştu.")


# 7. TAKİP İSTEKLERİ
with tab_istek:
    st.title("Gelen Takip İstekleri")
    reqs = []
    if supabase:
        try:
            reqs = (
                supabase.table("follows")
                .select("*")
                .eq("following", st.session_state.username)
                .eq("status", "pending")
                .execute()
                .data
            )
        except:
            pass

    if reqs:
        for r in reqs:
            f_profile = get_user_profile(r["follower"])
            f_disp = f_profile.get("full_name") or r["follower"]
            f_avat = f_profile.get("avatar_url")

            col_r1, col_r2 = st.columns([1, 8])
            with col_r1:
                if f_avat:
                    st.image(f_avat, width=50)
                else:
                    st.markdown("👤")
            with col_r2:
                st.write(f"**{f_disp}** (@{r['follower']}) sana takip isteği attı.")
                col1, col2, col3 = st.columns([1, 1, 1])
                with col1:
                    if st.button("Kabul Et", key=f"acc_{r['follower']}"):
                        supabase.table("follows").update({"status": "accepted"}).eq(
                            "id", r["id"]
                        ).execute()
                        st.success("İstek kabul edildi!")
                        st.rerun()
                with col2:
                    if st.button("Reddet", key=f"rej_{r['follower']}"):
                        supabase.table("follows").delete().eq("id", r["id"]).execute()
                        st.rerun()
                with col3:
                    if st.button("Engelle", key=f"blk_{r['follower']}"):
                        supabase.table("blocks").insert({
                            "blocker": st.session_state.username,
                            "blocked": r["follower"],
                        }).execute()
                        supabase.table("follows").delete().eq("id", r["id"]).execute()
                        st.success("Kullanıcı engellendi.")
                        st.rerun()
            st.divider()
    else:
        st.info("Bekleyen takip isteğin yok.")


# 8. ARKADAŞLARIM
with tab_arkadas:
    col_head1, col_head2 = st.columns([6, 1])
    with col_head1:
        st.title("Arkadaşlarım ve Listeleri")
    with col_head2:
        if st.button("🔄 Yenile", key="btn_refresh_friends"):
            st.rerun()

    friends = get_accepted_friends(st.session_state.username)

    if friends:
        friend_profiles = {f: get_user_profile(f) for f in friends}
        selected_friend = st.selectbox(
            "Bir arkadaş seç ve listelerini incele:",
            friends,
            format_func=lambda x: f"@{x} ({friend_profiles[x].get('full_name', '')})",
            key="friend_list_box",
        )
        if selected_friend:
            f_prof = friend_profiles[selected_friend]
            col_f1, col_f2 = st.columns([1, 8])
            with col_f1:
                if f_prof.get("avatar_url"):
                    st.image(f_prof["avatar_url"], width=60)
                else:
                    st.markdown("👤")
            with col_f2:
                st.subheader(
                    f"@{selected_friend} ({f_prof.get('full_name', '')}) Kişisinin"
                    " Listeleri"
                )

            f_favs = get_user_lists(selected_friend, "favorites")
            f_watch = get_user_lists(selected_friend, "watchlist")
            f_watched = get_user_lists(selected_friend, "watched")

            f_fav_movies = [i for i in f_favs if i["media_type"] == "Film"]
            f_fav_shows = [i for i in f_favs if i["media_type"] == "Dizi"]
            f_fav_actors = [i for i in f_favs if i["media_type"] == "Oyuncu"]

            f_w_movies = [i for i in f_watch if i["media_type"] == "Film"]
            f_w_shows = [i for i in f_watch if i["media_type"] == "Dizi"]

            f_wd_movies = [i for i in f_watched if i["media_type"] == "Film"]
            f_wd_shows = [i for i in f_watched if i["media_type"] == "Dizi"]

            st.markdown("---")
            st.write("❤️ **Favori Filmleri:**")
            if f_fav_movies:
                for it in f_fav_movies:
                    col_fm1, col_fm2, col_fm3 = st.columns([1, 5, 2])
                    with col_fm1:
                        if it.get("poster"):
                            st.image(it["poster"], width=60)
                    with col_fm2:
                        st.write(f"**{it['title']}**")
                    with col_fm3:
                        with st.popover("Paylaş"):
                            st.write("Kime gönderilsin?")
                            if friends:
                                tf = st.selectbox("Arkadaş", friends, key=f"ff_mov_{it['title']}")
                                if st.button("Gönder", key=f"btn_ff_mov_{it['title']}"):
                                    send_media_to_chat(tf, it['title'], "Film")
                            else:
                                st.warning("Arkadaşın yok.")
            else:
                st.write("Boş.")

            st.write("❤️ **Favori Dizileri:**")
            if f_fav_shows:
                for it in f_fav_shows:
                    col_fs1, col_fs2, col_fs3 = st.columns([1, 5, 2])
                    with col_fs1:
                        if it.get("poster"):
                            st.image(it["poster"], width=60)
                    with col_fs2:
                        st.write(f"**{it['title']}**")
                    with col_fs3:
                        with st.popover("Paylaş"):
                            st.write("Kime gönderilsin?")
                            if friends:
                                tf = st.selectbox("Arkadaş", friends, key=f"ff_sho_{it['title']}")
                                if st.button("Gönder", key=f"btn_ff_sho_{it['title']}"):
                                    send_media_to_chat(tf, it['title'], "Dizi")
                            else:
                                st.warning("Arkadaşın yok.")
            else:
                st.write("Boş.")

            st.write("❤️ **Favori Oyuncuları:**")
            if f_fav_actors:
                for it in f_fav_actors:
                    col_fa1, col_fa2, col_fa3 = st.columns([1, 5, 2])
                    with col_fa1:
                        if it.get("poster"):
                            st.image(it["poster"], width=60)
                    with col_fa2:
                        st.write(f"**{it['title']}**")
                    with col_fa3:
                        with st.popover("Paylaş"):
                            st.write("Kime gönderilsin?")
                            if friends:
                                tf = st.selectbox("Arkadaş", friends, key=f"ff_act_{it['title']}")
                                if st.button("Gönder", key=f"btn_ff_act_{it['title']}"):
                                    send_media_to_chat(tf, it['title'], "Oyuncu")
                            else:
                                st.warning("Arkadaşın yok.")
            else:
                st.write("Boş.")

            st.markdown("---")
            st.write("📌 **İzleyeceği Filmler:**")
            if f_w_movies:
                for it in f_w_movies:
                    c1, c2 = st.columns([6, 2])
                    with c1:
                        st.write(f"- {it['title']}")
                    with c2:
                        with st.popover("Paylaş"):
                            st.write("Kime gönderilsin?")
                            if friends:
                                tf = st.selectbox("Arkadaş", friends, key=f"fw_mov_{it['title']}")
                                if st.button("Gönder", key=f"btn_fw_mov_{it['title']}"):
                                    send_media_to_chat(tf, it['title'], "Film")
                            else:
                                st.warning("Arkadaşın yok.")
            else:
                st.write("Boş.")

            st.write("📌 **İzleyeceği Diziler:**")
            if f_w_shows:
                for it in f_w_shows:
                    c1, c2 = st.columns([6, 2])
                    with c1:
                        st.write(f"- {it['title']}")
                    with c2:
                        with st.popover("Paylaş"):
                            st.write("Kime gönderilsin?")
                            if friends:
                                tf = st.selectbox("Arkadaş", friends, key=f"fw_sho_{it['title']}")
                                if st.button("Gönder", key=f"btn_fw_sho_{it['title']}"):
                                    send_media_to_chat(tf, it['title'], "Dizi")
                            else:
                                st.warning("Arkadaşın yok.")
            else:
                st.write("Boş.")

            st.markdown("---")
            st.write("✅ **İzlediği Filmler:**")
            if f_wd_movies:
                for it in f_wd_movies:
                    c1, c2 = st.columns([6, 2])
                    with c1:
                        st.write(f"- {it['title']}")
                    with c2:
                        with st.popover("Paylaş"):
                            st.write("Kime gönderilsin?")
                            if friends:
                                tf = st.selectbox("Arkadaş", friends, key=f"fwd_mov_{it['title']}")
                                if st.button("Gönder", key=f"btn_fwd_mov_{it['title']}"):
                                    send_media_to_chat(tf, it['title'], "Film")
                            else:
                                st.warning("Arkadaşın yok.")
            else:
                st.write("Boş.")

            st.write("✅ **İzlediği Diziler:**")
            if f_wd_shows:
                for it in f_wd_shows:
                    c1, c2 = st.columns([6, 2])
                    with c1:
                        st.write(f"- {it['title']}")
                    with c2:
                        with st.popover("Paylaş"):
                            st.write("Kime gönderilsin?")
                            if friends:
                                tf = st.selectbox("Arkadaş", friends, key=f"fwd_sho_{it['title']}")
                                if st.button("Gönder", key=f"btn_fwd_sho_{it['title']}"):
                                    send_media_to_chat(tf, it['title'], "Dizi")
                            else:
                                st.warning("Arkadaşın yok.")
            else:
                st.write("Boş.")
    else:
        st.info("Henüz ekli bir arkadaşın yok.")


# 9. SOHBET ODASI
with tab_sohbet:
    st.title("Sohbet Odası")

    friends = get_accepted_friends(st.session_state.username)
    
    if friends:
        friend_profiles = {f: get_user_profile(f) for f in friends}
        chat_partner = st.selectbox(
            "Sohbet edilecek arkadaşı seç:",
            friends,
            format_func=lambda x: f"@{x} ({friend_profiles[x].get('full_name', '')})",
            key="chat_partner_box",
        )
        if chat_partner:
            msgs = []
            if supabase:
                try:
                    msgs = (
                        supabase.table("chats")
                        .select("*")
                        .or_(
                            f"and(sender.eq.{st.session_state.username},receiver.eq.{chat_partner}),and(sender.eq.{chat_partner},receiver.eq.{st.session_state.username})"
                        )
                        .order("created_at")
                        .execute()
                        .data
                    )
                except:
                    pass

            chat_container = st.container(height=400)
            with chat_container:
                if msgs:
                    for m in msgs:
                        sender_name = (
                            "Sen" if m["sender"] == st.session_state.username else m["sender"]
                        )
                        col_m1, col_m2 = st.columns([10, 2])
                        with col_m1:
                            st.write(f"**{sender_name}:** {m['message']}")
                        with col_m2:
                            if m["sender"] == st.session_state.username:
                                if st.button("Sil", key=f"del_m_{m['id']}"):
                                    supabase.table("chats").delete().eq("id", m["id"]).execute()
                                    st.rerun()
                else:
                    st.info("Henüz mesaj yok. İlk mesajı sen gönder!")

            with st.form(key="chat_form", clear_on_submit=True):
                msg_text = st.text_input("Mesajını yaz...", placeholder="Bir şeyler yaz...")
                col_sub1, col_sub2 = st.columns([6, 1])
                with col_sub1:
                    submit_btn = st.form_submit_button("Gönder", use_container_width=True)
                with col_sub2:
                    refresh_btn = st.form_submit_button("🔄", use_container_width=True)

                if submit_btn and msg_text.strip():
                    if supabase:
                        supabase.table("chats").insert({
                            "sender": st.session_state.username,
                            "receiver": chat_partner,
                            "message": msg_text.strip(),
                        }).execute()
                        st.rerun()
                
                if refresh_btn:
                    st.rerun()
    else:
        st.info("Sohbet etmek için önce biriyle takipleşmelisin.")