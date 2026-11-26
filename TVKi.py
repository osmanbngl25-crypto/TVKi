from datetime import datetime, timedelta
import random
import re
from ddgs import DDGS
from openai import OpenAI
import requests
from supabase import create_client
import streamlit as st

st.set_page_config(
    page_title="TVKi",
    page_icon="logo.png",
    layout="wide",
)

st.markdown(
    """
    <style>
    .stApp { background-color: #121212; color: #e0e0e0; }
    h1, h2, h3 { color: #ffffff !important; }
    
    /* Sadece input alanlarının iOS'te zoom yapmasını engelleyen güvenli ayar */
    .stTextInput input, .stTextArea textarea { 
        background-color: #1e1e1e !important; 
        color: white !important; 
        border-radius: 8px !important;
        font-size: 16px !important; 
    }
    </style>

    <script>
    (function() {
        function showScreenError(title, detail) {
            var box = document.getElementById("tvki-debug-box");
            if (!box) {
                box = document.createElement("div");
                box.id = "tvki-debug-box";
                box.style.cssText = "position:fixed;top:0;left:0;right:0;z-index:999999;background:#b71c1c;color:#fff;padding:12px;font-family:monospace;font-size:12px;max-height:50vh;overflow:auto;word-break:break-word;";
                (document.body || document.documentElement).appendChild(box);
            }
            var item = document.createElement("div");
            item.style.marginBottom = "8px";
            item.textContent = "[" + title + "] " + detail;
            box.appendChild(item);
        }

        window.addEventListener("error", function(e) {
            var msg = (e && e.message) ? e.message : "Bilinmeyen JS hatası";
            var src = (e && e.filename) ? (" (" + e.filename + ":" + e.lineno + ")") : "";
            showScreenError("JS ERROR", msg + src);
        }, true);

        window.addEventListener("unhandledrejection", function(e) {
            var reason = (e && e.reason) ? (e.reason.stack || e.reason.message || String(e.reason)) : "Promise reddedildi";
            showScreenError("PROMISE ERROR", reason);
        });
    })();
    </script>
""",
    unsafe_allow_html=True,
)

SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
TMDB_API_KEY = st.secrets["TMDB_API_KEY"]
GROQ_API_KEY = st.secrets["GROQ_API_KEY"]


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

# Ne İzlemeliyim için cache / oturum bazlı liste tutucu
if "wiz_results_cache" not in st.session_state:
  st.session_state.wiz_results_cache = []
if "wiz_last_genre" not in st.session_state:
  st.session_state.wiz_last_genre = None
if "wiz_last_type" not in st.session_state:
  st.session_state.wiz_last_type = None
if "wiz_nonce" not in st.session_state:
  st.session_state.wiz_nonce = 0

# Tarayıcı Hafızasından Oturum Kurtarma (Kalıcı Giriş Ekstresi)
if "username" in st.query_params and not st.session_state.logged_in:
  saved_uname = str(st.query_params["username"]).strip()
  if saved_uname and supabase:
    try:
      chk_user = (
          supabase.table("users")
          .select("username")
          .eq("username", saved_uname)
          .limit(1)
          .execute()
      )
      if chk_user.data:
        st.session_state.logged_in = True
        st.session_state.username = saved_uname
    except Exception:
      pass

if st.session_state.logged_in and st.session_state.username:
  if st.query_params.get("username") != st.session_state.username:
    st.query_params["username"] = st.session_state.username
elif "username" in st.query_params:
  del st.query_params["username"]

# --- GİRİŞ / KAYIT Ekranı ---
if not st.session_state.logged_in:
  st.title("TVKi")
  st.write("Sosyal film platformuna hoş geldin!")

  if supabase is None:
    st.error("⚠ Sunucu bağlantısı kurulamadı.")

  secim = st.radio("İşlem Türü:", ["Giriş Yap", "Kayıt Ol"], key="auth_radio")
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
              .select("username")
              .eq("username", k_adi)
              .limit(1)
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
              .select("username")
              .eq("username", k_adi)
              .eq("password", sifre)
              .limit(1)
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
@st.cache_data(ttl=600)
def _cached_user_lists(uname, l_type):
  if not supabase:
    return []
  try:
    res = (
        supabase.table("user_lists")
        .select("title, media_type, poster, progress")
        .eq("username", uname)
        .eq("list_type", l_type)
        .execute()
    )
    return res.data
  except Exception:
    try:
      res = (
          supabase.table("user_lists")
          .select("title, media_type, poster")
          .eq("username", uname)
          .eq("list_type", l_type)
          .execute()
      )
      return res.data
    except Exception:
      return []


def get_user_lists(uname, l_type):
  return _cached_user_lists(uname, l_type)


@st.cache_data(ttl=600)
def _cached_user_profile(uname):
  if not supabase:
    return {"username": uname, "full_name": "", "avatar_url": ""}
  try:
    res = (
        supabase.table("users")
        .select("username, full_name, avatar_url")
        .eq("username", uname)
        .limit(1)
        .execute()
    )
    if res.data:
      return res.data[0]
  except Exception:
    pass
  return {"username": uname, "full_name": "", "avatar_url": ""}


def get_user_profile(uname):
  return _cached_user_profile(uname)


@st.cache_data(ttl=600)
def _cached_accepted_friends(uname):
  if not supabase:
    return []
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
  except Exception:
    return []


def get_accepted_friends(uname):
  return _cached_accepted_friends(uname)


@st.cache_data(ttl=30)
def _cached_chat_messages(user_a, user_b):
  if not supabase or not user_a or not user_b:
    return []
  try:
    return (
        supabase.table("chats")
        .select("sender, message, created_at")
        .or_(
            f"and(sender.eq.{user_a},receiver.eq.{user_b}),and(sender.eq.{user_b},receiver.eq.{user_a})"
        )
        .order("created_at")
        .execute()
        .data
    )
  except Exception:
    return []


def invalidate_user_caches():
  try:
    _cached_user_lists.clear()
    _cached_user_profile.clear()
    _cached_accepted_friends.clear()
    _cached_chat_messages.clear()
  except Exception:
    pass


def normalize_title_for_match(title_str):
  if not title_str:
    return ""
  cleaned = re.sub(r"\(\d{4}\)", "", title_str).strip().lower()
  cleaned = re.sub(r"\s+", " ", cleaned)
  return cleaned


def detect_sequel_number(raw_title):
  if not raw_title:
    return None
  t = raw_title.lower().strip()
  m = re.search(
      r"(?:\b(?:bölüm|kısım|part|vol\.?|chapter)\s*|\s+)([2-9]|1\d)\b", t
  )
  if m:
    return int(m.group(1))
  roman_map = {"ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6}
  for rom, num in roman_map.items():
    if re.search(rf"\b{rom}\b", t):
      return num
  return None


def base_series_key(raw_title):
  if not raw_title:
    return ""
  t = re.sub(r"\(\d{4}\)", "", raw_title).lower().strip()
  t = re.sub(r"\b(bölüm|kısım|part|vol\.?|chapter)\s*\d+\b", "", t)
  t = re.sub(r"\b(ii|iii|iv|v|vi)\b", "", t)
  t = re.sub(r"\s+\d+$", "", t)
  t = re.sub(r"[:\-–—]+.*$", "", t)
  return re.sub(r"\s+", " ", t).strip()


def send_media_to_chat(receiver, media_title, media_type):
  if not supabase:
    return
  try:
    msg = f"🎬 Seninle bir yapım paylaştı: **{media_title}** ({media_type})"
    supabase.table("chats").insert({
        "sender": st.session_state.username,
        "receiver": receiver,
        "message": msg,
    }).execute()
    _cached_chat_messages.clear()
    st.success(f"@{receiver} kişisine sohbet üzerinden gönderildi!")
  except Exception as e:
    st.error(f"Gönderilemedi: {e}")


@st.cache_data(ttl=600)
def get_movie_cast_detailed(media_id, tmdb_type):
  try:
    url = f"https://api.themoviedb.org/3/{tmdb_type}/{media_id}/credits?api_key={TMDB_API_KEY}&language=tr-TR"
    res = requests.get(url, timeout=6).json()
    cast = res.get("cast", [])
    actors = []
    for actor in cast:
      name = actor.get("name")
      actor_id = actor.get("id")
      profile_path = actor.get("profile_path")
      profile_url = (
          f"https://image.tmdb.org/t/p/w200{profile_path}"
          if profile_path
          else None
      )
      actors.append({"id": actor_id, "name": name, "poster": profile_url})
    return actors
  except Exception:
    return []


@st.cache_data(ttl=600)
def get_actor_filmography(actor_id):
  try:
    url = f"https://api.themoviedb.org/3/person/{actor_id}/combined_credits?api_key={TMDB_API_KEY}&language=tr-TR"
    res = requests.get(url, timeout=6).json()
    cast_list = res.get("cast", [])

    valid_media = []
    for item in cast_list:
      m_type = item.get("media_type")
      if m_type not in ["movie", "tv"]:
        continue

      title = item.get("title") if m_type == "movie" else item.get("name")
      date_str = (
          item.get("release_date")
          if m_type == "movie"
          else item.get("first_air_date")
      )
      year = date_str[:4] if date_str and len(date_str) >= 4 else "0000"
      poster_path = item.get("poster_path")
      poster_url = (
          f"https://image.tmdb.org/t/p/w500{poster_path}"
          if poster_path
          else None
      )

      valid_media.append({
          "id": item.get("id"),
          "title": f"{title} ({year})" if year != "0000" else title,
          "year": year,
          "type": "Film" if m_type == "movie" else "Dizi",
          "poster": poster_url,
      })

    valid_media.sort(key=lambda x: x["year"], reverse=True)
    return valid_media
  except Exception:
    return []


@st.cache_data(ttl=600)
def get_media_trailer(media_id, tmdb_type):
  try:
    url = f"https://api.themoviedb.org/3/{tmdb_type}/{media_id}/videos?api_key={TMDB_API_KEY}&language=tr-TR"
    res = requests.get(url, timeout=5).json().get("results", [])
    for vid in res:
      if vid.get("site") == "YouTube" and vid.get("type") in [
          "Trailer",
          "Teaser",
      ]:
        return f"https://www.youtube.com/watch?v={vid.get('key')}"

    url_en = f"https://api.themoviedb.org/3/{tmdb_type}/{media_id}/videos?api_key={TMDB_API_KEY}&language=en-US"
    res_en = requests.get(url_en, timeout=5).json().get("results", [])
    for vid in res_en:
      if vid.get("site") == "YouTube" and vid.get("type") in [
          "Trailer",
          "Teaser",
      ]:
        return f"https://www.youtube.com/watch?v={vid.get('key')}"
  except Exception:
    pass
  return None


@st.cache_data(ttl=1800)
def get_tmdb_genres(tmdb_type):
  try:
    g_url = f"https://api.themoviedb.org/3/genre/{tmdb_type}/list?api_key={TMDB_API_KEY}&language=tr-TR"
    g_res = requests.get(g_url, timeout=5).json()
    return {g["name"]: g["id"] for g in g_res.get("genres", [])}
  except Exception:
    return {}


@st.cache_data(ttl=3600)
def _cached_movie_collection_first_part(movie_id):
  try:
    m_detail_url = f"https://api.themoviedb.org/3/movie/{movie_id}?api_key={TMDB_API_KEY}&language=tr-TR"
    m_detail = requests.get(m_detail_url, timeout=4).json()
    coll = m_detail.get("belongs_to_collection")
    if coll and coll.get("id"):
      coll_url = f"https://api.themoviedb.org/3/collection/{coll['id']}?api_key={TMDB_API_KEY}&language=tr-TR"
      parts = requests.get(coll_url, timeout=4).json().get("parts", [])
      dated_parts = [p for p in parts if p.get("release_date")]
      dated_parts.sort(key=lambda x: x.get("release_date", ""))
      if dated_parts and len(dated_parts) > 1:
        first_part = dated_parts[0]
        return {
            "first_id": first_part.get("id"),
            "first_title": first_part.get("title", ""),
        }
  except Exception:
    pass
  return None


CUSTOM_GENRE_LIST = [
    "Aksiyon",
    "Macera",
    "Animasyon",
    "Komedi",
    "Suç",
    "Belgesel",
    "Dram",
    "Aile",
    "Fantastik",
    "Tarih",
    "Korku",
    "Müzik",
    "Gizem",
    "Romantik",
    "Bilim-Kurgu",
    "Gerilim",
    "Savaş",
    "Vahşi Batı",
    "K-Drama",
    "Anime",
    "Müzikal",
    "Biyografi",
    "Spor",
    "Marvel",
    "DC",
]

STANDARD_GENRE_IDS = {
    "Aksiyon": {"movie": "28", "tv": "10759"},
    "Macera": {"movie": "12", "tv": "10759"},
    "Animasyon": {"movie": "16", "tv": "16"},
    "Komedi": {"movie": "35", "tv": "35"},
    "Suç": {"movie": "80", "tv": "80"},
    "Belgesel": {"movie": "99", "tv": "99"},
    "Dram": {"movie": "18", "tv": "18"},
    "Aile": {"movie": "10751", "tv": "10751"},
    "Fantastik": {"movie": "14", "tv": "10765"},
    "Tarih": {"movie": "36", "tv": "36"},
    "Korku": {"movie": "27", "tv": "9648"},
    "Müzik": {"movie": "10402", "tv": "10402"},
    "Gizem": {"movie": "9648", "tv": "9648"},
    "Romantik": {"movie": "10749", "tv": "10749"},
    "Bilim-Kurgu": {"movie": "878", "tv": "10765"},
    "Gerilim": {"movie": "53", "tv": "80"},
    "Savaş": {"movie": "10752", "tv": "10768"},
    "Vahşi Batı": {"movie": "37", "tv": "37"},
}


def build_discover_filter_query(tmdb_t_type, selected_genre_name, genres_dict):
  if not selected_genre_name:
    return ""

  if selected_genre_name == "K-Drama":
    drama_id = genres_dict.get("Dram") or genres_dict.get("Drama") or "18"
    return f"&with_origin_country=KR&with_genres={drama_id}"

  if selected_genre_name == "Anime":
    return "&with_genres=16&with_origin_country=JP"

  if selected_genre_name == "Müzikal":
    return "&with_keywords=4344"

  if selected_genre_name == "Biyografi":
    return "&with_keywords=9672|5565"

  if selected_genre_name == "Spor":
    return "&with_keywords=6075"

  if selected_genre_name == "Marvel":
    return "&with_companies=420|7505|19551"

  if selected_genre_name == "DC":
    return "&with_companies=9993|128064|184898|429"

  g_id = genres_dict.get(selected_genre_name)
  if not g_id and selected_genre_name in STANDARD_GENRE_IDS:
    g_id = STANDARD_GENRE_IDS[selected_genre_name].get(tmdb_t_type)

  if g_id:
    return f"&with_genres={g_id}"

  return ""


def is_sequel_without_first_watched(
    item, tmdb_t_type, watched_titles_norm, watched_series_bases
):
  raw_title = item.get("title") if tmdb_t_type == "movie" else item.get("name")
  if not raw_title:
    return False

  seq_num = detect_sequel_number(raw_title)
  b_key = base_series_key(raw_title)

  if seq_num and seq_num >= 2:
    if b_key and b_key not in watched_series_bases:
      return True

  if tmdb_t_type == "movie" and item.get("id"):
    first_info = _cached_movie_collection_first_part(item["id"])
    if first_info and first_info.get("first_id") != item.get("id"):
      f_title_norm = normalize_title_for_match(first_info.get("first_title", ""))
      f_base = base_series_key(first_info.get("first_title", ""))
      if f_title_norm not in watched_titles_norm and (
          not f_base or f_base not in watched_series_bases
      ):
        return True

  return False


def fetch_quality_recommendations(
    uname,
    wiz_type,
    tmdb_t_type,
    selected_genre_name,
    genres_dict,
    seed_nonce=0,
):
  watched_items = get_user_lists(uname, "watched")
  fav_items = get_user_lists(uname, "favorites")

  excluded_norm = set()
  watched_norm = set()
  watched_bases = set()

  for w in watched_items:
    t_norm = normalize_title_for_match(w.get("title", ""))
    if t_norm:
      excluded_norm.add(t_norm)
      watched_norm.add(t_norm)
      b = base_series_key(w.get("title", ""))
      if b:
        watched_bases.add(b)

  for f in fav_items:
    t_norm = normalize_title_for_match(f.get("title", ""))
    if t_norm:
      excluded_norm.add(t_norm)

  filter_query = build_discover_filter_query(
      tmdb_t_type, selected_genre_name, genres_dict
  )
  is_niche = selected_genre_name in [
      "Marvel",
      "DC",
      "Müzikal",
      "Biyografi",
      "Spor",
      "Anime",
      "K-Drama",
  ]
  max_page = 5 if is_niche else 10
  min_votes = 40 if is_niche else 150

  rng = random.Random(f"{uname}-{wiz_type}-{selected_genre_name}-{seed_nonce}")
  candidate_pool = []
  pages_to_try = rng.sample(range(1, max_page + 1), k=min(2, max_page))

  for pg in pages_to_try:
    params = (
        f"api_key={TMDB_API_KEY}&language=tr-TR"
        f"&sort_by=popularity.desc&vote_count.gte={min_votes}&vote_average.gte=6.0&page={pg}"
        f"{filter_query}"
    )

    try:
      url = f"https://api.themoviedb.org/3/discover/{tmdb_t_type}?{params}"
      resp = requests.get(url, timeout=6)
      if resp.status_code == 200:
        results = resp.json().get("results", [])
        for r in results:
          raw_t = r.get("title") if tmdb_t_type == "movie" else r.get("name")
          if not raw_t or not r.get("poster_path"):
            continue
          if normalize_title_for_match(raw_t) in excluded_norm:
            continue
          candidate_pool.append(r)
    except Exception:
      continue

  if len(candidate_pool) < 10:
    try:
      fallback_params = (
          f"api_key={TMDB_API_KEY}&language=tr-TR"
          f"&sort_by=popularity.desc&vote_count.gte=10&vote_average.gte=5.0&page=1"
          f"{filter_query}"
      )
      url_fb = f"https://api.themoviedb.org/3/discover/{tmdb_t_type}?{fallback_params}"
      resp_fb = requests.get(url_fb, timeout=6)
      if resp_fb.status_code == 200:
        for r in resp_fb.json().get("results", []):
          raw_t = r.get("title") if tmdb_t_type == "movie" else r.get("name")
          if (
              raw_t
              and r.get("poster_path")
              and normalize_title_for_match(raw_t) not in excluded_norm
          ):
            candidate_pool.append(r)
    except Exception:
      pass

  seen_ids = set()
  unique_pool = []
  for r in candidate_pool:
    rid = r.get("id")
    if rid not in seen_ids:
      seen_ids.add(rid)
      unique_pool.append(r)

  rng.shuffle(unique_pool)

  final_picks = []
  checked_count = 0
  for item in unique_pool:
    if checked_count >= 16:
      break
    checked_count += 1
    if is_sequel_without_first_watched(
        item, tmdb_t_type, watched_norm, watched_bases
    ):
      continue
    final_picks.append(item)
    if len(final_picks) >= 10:
      break

  return final_picks


def add_to_list(l_type, m_data):
  if not supabase:
    return
  try:
    m_type = m_data.get("media_type") or m_data.get("type", "Film")
    m_title = m_data["title"]

    chk = (
        supabase.table("user_lists")
        .select("title")
        .eq("username", st.session_state.username)
        .eq("list_type", l_type)
        .eq("title", m_title)
        .execute()
    )
    if not chk.data:
      try:
        supabase.table("user_lists").insert({
            "username": st.session_state.username,
            "list_type": l_type,
            "title": m_title,
            "media_type": m_type,
            "poster": m_data.get("poster"),
            "progress": "",
        }).execute()
      except Exception:
        supabase.table("user_lists").insert({
            "username": st.session_state.username,
            "list_type": l_type,
            "title": m_title,
            "media_type": m_type,
            "poster": m_data.get("poster"),
        }).execute()

    if l_type == "watched":
      try:
        supabase.table("user_lists").delete().eq(
            "username", st.session_state.username
        ).eq("list_type", "watchlist").eq("title", m_title).execute()
      except Exception:
        pass

    invalidate_user_caches()
  except Exception as e:
    st.error(f"Hata: {e}")


def update_progress_in_db(l_type, title, progress_val):
  if not supabase:
    return
  try:
    supabase.table("user_lists").update({"progress": progress_val}).eq(
        "username", st.session_state.username
    ).eq("list_type", l_type).eq("title", title).execute()
    invalidate_user_caches()
  except Exception as e:
    st.error(f"Kayıt hatası: {e}")


def remove_from_list(l_type, title):
  if not supabase:
    return
  try:
    supabase.table("user_lists").delete().eq(
        "username", st.session_state.username
    ).eq("list_type", l_type).eq("title", title).execute()
    invalidate_user_caches()
  except Exception as e:
    st.error(f"Hata: {e}")


current_user_profile = get_user_profile(st.session_state.username)
c_name = current_user_profile.get("full_name") or st.session_state.username
c_avatar = current_user_profile.get("avatar_url")
shared_friends_list = get_accepted_friends(st.session_state.username)

# --- ÜST BAR ---
top_col1, top_col2 = st.columns([8, 2])
with top_col1:
  cols_h = st.columns([1, 10])
  with cols_h[0]:
    if c_avatar:
      st.image(c_avatar, width=45)
    else:
      try:
        st.image("logo.png", width=45)
      except Exception:
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
    tab_ne_izlesem,
    tab_fav,
    tab_watch,
    tab_watched,
    tab_yarida,
    tab_profil,
    tab_ara,
    tab_istek,
    tab_arkadas,
    tab_sohbet,
    tab_kio,
) = st.tabs([
    "🏠 Ana Sayfa",
    "✨ Ne İzlemeliyim?",
    "❤️ Favoriler",
    "📌 İzlenecek",
    "✅ İzlenen",
    "⏳ Yarıda Kalanlar",
    "👤 Profil",
    "🔍 Kullanıcı Ara",
    "📩 İstekler",
    "👥 Arkadaşlar",
    "💬 Sohbet",
    "🤖 KIO AI",
])


# 1. ANA SAYFA / ARAMA
with tab_ana:
  if st.session_state.search_query_override:
    st.session_state.ana_media_type = "Oyuncu"
    st.session_state.ana_search_actor = st.session_state.search_query_override
    st.session_state.search_query_override = ""

  media_type = st.selectbox(
      "Kategori Seç", ["Film", "Dizi", "Oyuncu"], key="ana_media_type"
  )

  if media_type == "Oyuncu":
    search_query = st.text_input(
        "🔍 Oyuncu adı arat...",
        placeholder="Örn: Adam Sandler, Leonardo DiCaprio...",
        key="ana_search_actor",
    )
    if search_query:
      try:
        url = f"https://api.themoviedb.org/3/search/person?api_key={TMDB_API_KEY}&language=tr-TR&query={search_query}"
        res = requests.get(url, timeout=6).json().get("results", [])

        if res:
          friends_list = shared_friends_list
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
                "media_type": "Oyuncu",
                "poster": poster_url,
            }

            col_act1, col_act2 = st.columns([2, 8])
            with col_act1:
              if st.button("❤️ Favori", key=f"f_actor_{index}"):
                add_to_list("favorites", m_data)
                st.success("Oyuncu favorilere eklendi!")
                st.rerun()

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
                        target_f = st.selectbox(
                            "Arkadaş",
                            friends_list,
                            key=f"shr_mov_{actor_id}_{m_idx}",
                        )
                        if st.button(
                            "Sohbete Gönder",
                            key=f"btn_shr_mov_{actor_id}_{m_idx}",
                        ):
                          send_media_to_chat(target_f, mov["title"], "Film")
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
                        target_f = st.selectbox(
                            "Arkadaş",
                            friends_list,
                            key=f"shr_sho_{actor_id}_{s_idx}",
                        )
                        if st.button(
                            "Sohbete Gönder",
                            key=f"btn_shr_sho_{actor_id}_{s_idx}",
                        ):
                          send_media_to_chat(target_f, show["title"], "Dizi")
                      else:
                        st.warning("Henüz arkadaşın yok.")
              else:
                st.info("Dizi bulunamadı.")

            st.divider()
        else:
          st.warning("Oyuncu bulunamadı.")
      except Exception as e:
        st.error(f"Oyuncu araması yapılırken bağlantı kurulamadı: {e}")
  else:
    tmdb_type = "movie" if media_type == "Film" else "tv"

    last_search_key = f"last_query_{tmdb_type}"
    current_search_input = st.text_input(
        "🔍 Film veya dizi adı arat...",
        placeholder="Örn: Interstellar, Spider-Man...",
        key="ana_search",
    )

    if st.session_state.get(last_search_key) != current_search_input:
      st.session_state[last_search_key] = current_search_input
      for k in list(st.session_state.keys()):
        if k.startswith("show_trailer_") or k.startswith("show_cast_"):
          st.session_state[k] = False

    search_query = current_search_input

    if search_query:
      try:
        url = f"https://api.themoviedb.org/3/search/{tmdb_type}?api_key={TMDB_API_KEY}&language=tr-TR&query={search_query}"
        res = requests.get(url, timeout=6).json().get("results", [])

        if res:
          friends_list = shared_friends_list
          st.success(f"{len(res)} sonuç bulundu:")
          for index, item in enumerate(res):
            media_id = item.get("id")
            title = (
                item.get("title") if tmdb_type == "movie" else item.get("name")
            )
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
                "media_type": media_type,
                "poster": poster_url,
            }

            col1, col2, col3, col4, col5, col6, col7 = st.columns(7)
            with col1:
              if st.button("❤️ Favori", key=f"f_{index}"):
                add_to_list("favorites", m_data)
                st.success("Favorilere eklendi!")
                st.rerun()
            with col2:
              if st.button("📌 İzle", key=f"w_{index}"):
                add_to_list("watchlist", m_data)
                st.success("İzleneceklere eklendi!")
                st.rerun()
            with col3:
              if st.button("✅ İzledim", key=f"wd_{index}"):
                add_to_list("watched", m_data)
                st.success(
                    "İzlenenlere eklendi! (Varsa İzlenecek listesinden çıkarıldı)"
                )
                st.rerun()
            with col4:
              if st.button("⏳ Yarıda", key=f"half_{index}"):
                add_to_list("unfinished", m_data)
                st.success("Yarıda kalanlara eklendi!")
                st.rerun()
            with col5:
              with st.popover("📤 Paylaş", use_container_width=True):
                st.write("Kime gönderilsin?")
                if friends_list:
                  target_f = st.selectbox(
                      "Arkadaş", friends_list, key=f"share_sel_media_{index}"
                  )
                  if st.button(
                      "Sohbete Gönder", key=f"share_btn_media_{index}"
                  ):
                    send_media_to_chat(target_f, full_media_title, media_type)
                else:
                  st.warning("Henüz arkadaşın yok.")
            with col6:
              if st.button("🎭 Oyuncular", key=f"cast_btn_{index}"):
                st.session_state[f"show_cast_{index}"] = not st.session_state.get(
                    f"show_cast_{index}", False
                )
            with col7:
              if st.button("🎬 Fragman", key=f"trailer_btn_{index}"):
                st.session_state[f"show_trailer_{index}"] = (
                    not st.session_state.get(f"show_trailer_{index}", False)
                )

            if st.session_state.get(f"show_trailer_{index}", False):
              trailer_url = get_media_trailer(media_id, tmdb_type)
              if trailer_url:
                st.video(trailer_url)
              else:
                st.info("Bu yapım için fragman bulunamadı.")

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
                    if st.button(
                        "🧭", key=f"compass_{media_id}_{actor['id']}_{a_idx}"
                    ):
                      st.session_state.search_query_override = actor["name"]
                      st.rerun()
              else:
                st.info("Oyuncu bilgisi bulunamadı.")

            st.divider()
        else:
          st.warning("Sonuç bulunamadı.")
      except Exception as e:
        st.error(f"Film araması yapılırken bağlantı kurulamadı: {e}")


# 2. NE İZLEMELİYİM?
with tab_ne_izlesem:
  st.title("✨ Ne İzlemeliyim?")
  st.write(
      "Kararsız mı kaldın? İçerik türünü ve istediğin türü seç, sana sevilen"
      " ve kaliteli rastgele öneriler getirelim!"
  )

  col_wizard1, col_wizard2, col_wizard3 = st.columns([3, 4, 3])
  with col_wizard1:
    wiz_type = st.selectbox(
        "İçerik Türü", ["Film", "Dizi"], key="wiz_media_type"
    )

  tmdb_t_type = "movie" if wiz_type == "Film" else "tv"
  genres_dict = get_tmdb_genres(tmdb_t_type)

  with col_wizard2:
    genre_options = [""] + CUSTOM_GENRE_LIST
    selected_genre_name = st.selectbox(
        "Tür / Konu", genre_options, index=0, key="wiz_genre"
    )

  with col_wizard3:
    st.write("")
    st.write("")
    refresh_wizard = st.button(
        "🔄 Listeyi Yenile / Rastgele Getir",
        use_container_width=True,
        key="btn_wiz_refresh",
    )

  if refresh_wizard:
    st.session_state.wiz_nonce += 1

  if (
      st.session_state.wiz_last_genre != selected_genre_name
      or st.session_state.wiz_last_type != wiz_type
      or refresh_wizard
  ):
    st.session_state.wiz_last_genre = selected_genre_name
    st.session_state.wiz_last_type = wiz_type
    st.session_state.wiz_results_cache = []

    for k in list(st.session_state.keys()):
      if k.startswith("wiz_show_trailer_"):
        st.session_state[k] = False

    if selected_genre_name:
      st.session_state.wiz_results_cache = fetch_quality_recommendations(
          st.session_state.username,
          wiz_type,
          tmdb_t_type,
          selected_genre_name,
          genres_dict,
          st.session_state.wiz_nonce,
      )

  if not selected_genre_name:
    st.info("👆 Başlamak için yukarıdan lütfen bir Tür / Konu seç!")
  else:
    recommendations = st.session_state.wiz_results_cache
    if recommendations:
      st.success(
          f"Seçilen türe uygun {len(recommendations)} kaliteli öneri"
          " listeleniyor:"
      )
      friends_list = shared_friends_list

      for idx, item in enumerate(recommendations):
        media_id = item.get("id")
        title = (
            item.get("title") if tmdb_t_type == "movie" else item.get("name")
        )
        overview = item.get("overview")
        poster_path = item.get("poster_path")
        date_str = (
            item.get("release_date", "Bilinmiyor")
            if tmdb_t_type == "movie"
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
            "media_type": wiz_type,
            "poster": poster_url,
        }

        c_w1, c_w2, c_w3, c_w4, c_w5, c_w6 = st.columns(6)
        with c_w1:
          if st.button("❤ Favori", key=f"wiz_f_{idx}"):
            add_to_list("favorites", m_data)
            st.success("Favorilere eklendi!")
            st.rerun()
        with c_w2:
          if st.button("📌 İzle", key=f"wiz_w_{idx}"):
            add_to_list("watchlist", m_data)
            st.success("İzleneceklere eklendi!")
            st.rerun()
        with c_w3:
          if st.button("✅ İzledim", key=f"wiz_wd_{idx}"):
            add_to_list("watched", m_data)
            st.success(
                "İzlenenlere eklendi! (Varsa İzlenecek listesinden çıkarıldı)"
            )
            st.rerun()
        with c_w4:
          if st.button("⏳ Yarıda", key=f"wiz_half_{idx}"):
            add_to_list("unfinished", m_data)
            st.success("Yarıda kalanlara eklendi!")
            st.rerun()
        with c_w5:
          with st.popover("📤 Paylaş", use_container_width=True):
            st.write("Kime gönderilsin?")
            if friends_list:
              target_f = st.selectbox(
                  "Arkadaş", friends_list, key=f"wiz_share_{idx}"
              )
              if st.button("Sohbete Gönder", key=f"wiz_share_btn_{idx}"):
                send_media_to_chat(target_f, full_media_title, wiz_type)
            else:
              st.warning("Henüz arkadaşın yok.")
        with c_w6:
          if st.button("🎬 Fragman", key=f"wiz_trailer_btn_{idx}"):
            st.session_state[f"wiz_show_trailer_{idx}"] = (
                not st.session_state.get(f"wiz_show_trailer_{idx}", False)
            )

        if st.session_state.get(f"wiz_show_trailer_{idx}", False):
          trailer_url = get_media_trailer(media_id, tmdb_t_type)
          if trailer_url:
            st.video(trailer_url)
          else:
            st.info("Bu yapım için fragman bulunamadı.")

        st.divider()
    else:
      st.warning("Bu türde gösterilecek içerik bulunamadı.")


# 3. FAVORİLERİM
with tab_fav:
  st.title("Favorilerim")
  items = get_user_lists(st.session_state.username, "favorites")
  friends_list = shared_friends_list

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
            tf = st.selectbox(
                "Arkadaş", friends_list, key=f"p_fav_mov_{item['title']}"
            )
            if st.button("Gönder", key=f"btn_p_fav_mov_{item['title']}"):
              send_media_to_chat(tf, item["title"], "Film")
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
            tf = st.selectbox(
                "Arkadaş", friends_list, key=f"p_fav_sho_{item['title']}"
            )
            if st.button("Gönder", key=f"btn_p_fav_sho_{item['title']}"):
              send_media_to_chat(tf, item["title"], "Dizi")
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
            tf = st.selectbox(
                "Arkadaş", friends_list, key=f"p_fav_act_{item['title']}"
            )
            if st.button("Gönder", key=f"btn_p_fav_act_{item['title']}"):
              send_media_to_chat(tf, item["title"], "Oyuncu")
          else:
            st.warning("Arkadaşın yok.")
  else:
    st.info("Favori oyuncu bulunmuyor.")


# 4. İZLEYECEKLERİM
with tab_watch:
  st.title("İzleyecek Listen")
  items = get_user_lists(st.session_state.username, "watchlist")
  friends_list = shared_friends_list

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
            tf = st.selectbox(
                "Arkadaş", friends_list, key=f"p_wat_mov_{item['title']}"
            )
            if st.button("Gönder", key=f"btn_p_wat_mov_{item['title']}"):
              send_media_to_chat(tf, item["title"], "Film")
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
            tf = st.selectbox(
                "Arkadaş", friends_list, key=f"p_wat_sho_{item['title']}"
            )
            if st.button("Gönder", key=f"btn_p_wat_sho_{item['title']}"):
              send_media_to_chat(tf, item["title"], "Dizi")
          else:
            st.warning("Arkadaşın yok.")
  else:
    st.info("İzlenecek dizi bulunmuyor.")


# 5. İZLEDİKLERİM
with tab_watched:
  st.title("İzlediklerim")
  items = get_user_lists(st.session_state.username, "watched")
  friends_list = shared_friends_list

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
            tf = st.selectbox(
                "Arkadaş", friends_list, key=f"p_wed_mov_{item['title']}"
            )
            if st.button("Gönder", key=f"btn_p_wed_mov_{item['title']}"):
              send_media_to_chat(tf, item["title"], "Film")
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
            tf = st.selectbox(
                "Arkadaş", friends_list, key=f"p_wed_sho_{item['title']}"
            )
            if st.button("Gönder", key=f"btn_p_wed_sho_{item['title']}"):
              send_media_to_chat(tf, item["title"], "Dizi")
          else:
            st.warning("Arkadaşın yok.")
  else:
    st.info("İzlenen dizi bulunmuyor.")


# 6. YARIDA KALANLAR
with tab_yarida:
  st.title("Yarıda Kalanlar")
  items = get_user_lists(st.session_state.username, "unfinished")
  friends_list = shared_friends_list

  half_movies = [i for i in items if i["media_type"] == "Film"]
  half_shows = [i for i in items if i["media_type"] == "Dizi"]

  st.subheader("🎬 Filmler")
  if half_movies:
    for item in half_movies:
      st.write(f"⏳ **{item['title']}**")
      if item.get("poster"):
        st.image(item["poster"], width=100)

      current_prog = item.get("progress") or ""

      with st.form(key=f"form_half_mov_{item['title']}"):
        progress_val = st.text_input(
            "Kaldığın Anı Yaz (Örn: 1.25.32)",
            value=current_prog,
            placeholder="1.25.32",
            key=f"input_half_mov_{item['title']}",
        )
        submitted_mov = st.form_submit_button("Güncelle / Kaydet")
        if submitted_mov:
          update_progress_in_db("unfinished", item["title"], progress_val)
          st.success(
              f"**{item['title']}** için kaldığın yer ({progress_val})"
              " kaydedildi!"
          )
          st.rerun()

      c1, c2 = st.columns(2)
      with c1:
        if st.button("Listeden Kaldır", key=f"rem_half_mov_{item['title']}"):
          remove_from_list("unfinished", item["title"])
          st.rerun()
      with c2:
        with st.popover("Paylaş"):
          st.write("Kime gönderilsin?")
          if friends_list:
            tf = st.selectbox(
                "Arkadaş", friends_list, key=f"p_half_mov_{item['title']}"
            )
            if st.button("Gönder", key=f"btn_p_half_mov_{item['title']}"):
              send_media_to_chat(tf, item["title"], "Film")
          else:
            st.warning("Arkadaşın yok.")
  else:
    st.info("Yarıda kalan film bulunmuyor.")

  st.divider()

  st.subheader("📺 Diziler")
  if half_shows:
    for item in half_shows:
      st.write(f"⏳ **{item['title']}**")
      if item.get("poster"):
        st.image(item["poster"], width=100)

      current_prog_show = item.get("progress") or ""

      with st.form(key=f"form_half_sho_{item['title']}"):
        progress_val_show = st.text_input(
            "Kaldığın Sezon/Bölüm Yaz (Örn: 4.sezon 9.bölüm)",
            value=current_prog_show,
            placeholder="4.sezon 9.bölüm",
            key=f"input_half_sho_{item['title']}",
        )
        submitted_show = st.form_submit_button("Güncelle / Kaydet")
        if submitted_show:
          update_progress_in_db("unfinished", item["title"], progress_val_show)
          st.success(
              f"**{item['title']}** için kaldığın yer ({progress_val_show})"
              " kaydedildi!"
          )
          st.rerun()

      c1, c2 = st.columns(2)
      with c1:
        if st.button("Listeden Kaldır", key=f"rem_half_sho_{item['title']}"):
          remove_from_list("unfinished", item["title"])
          st.rerun()
      with c2:
        with st.popover("Paylaş"):
          st.write("Kime gönderilsin?")
          if friends_list:
            tf = st.selectbox(
                "Arkadaş", friends_list, key=f"p_half_sho_{item['title']}"
            )
            if st.button("Gönder", key=f"btn_p_half_sho_{item['title']}"):
              send_media_to_chat(tf, item["title"], "Dizi")
          else:
            st.warning("Arkadaşın yok.")
  else:
    st.info("Yarıda kalan dizi bulunmuyor.")


# 7. PROFİL & AYARLAR
with tab_profil:
  st.title("Profil Ayarları")
  user_info = current_user_profile

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
      invalidate_user_caches()
      st.success("Profil güncellendi!")
      st.rerun()

  followers = []
  following = shared_friends_list
  if supabase:
    try:
      followers = (
          supabase.table("follows")
          .select("follower")
          .eq("following", st.session_state.username)
          .eq("status", "accepted")
          .execute()
          .data
      )
    except Exception:
      pass
  st.write(
      f"👥 Takipçi: **{len(followers)}** | Takip Edilen: **{len(following)}**"
  )

  st.divider()
  st.error("⚠️ Tehlike Bölgesi")
  if st.button("Profili Kalıcı Olarak Sil"):
    if supabase:
      supabase.table("users").delete().eq(
          "username", st.session_state.username
      ).execute()
      invalidate_user_caches()
      st.session_state.logged_in = False
      st.session_state.username = ""
      if "username" in st.query_params:
        del st.query_params["username"]
      st.success("Profil ve tüm verilerin silindi.")
      st.rerun()


# 8. KULLANICI ARA
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
                  .select("status")
                  .eq("follower", st.session_state.username)
                  .eq("following", u["username"])
                  .limit(1)
                  .execute()
                  .data
              )
              if not existing_f:
                if st.button("Takip İsteği Gönder", key=f"req_{u['username']}"):
                  supabase.table("follows").insert({
                      "follower": st.session_state.username,
                      "following": u["username"],
                      "status": "pending",
                  }).execute()
                  invalidate_user_caches()
                  st.success("İstek gönderildi!")
                  st.rerun()
              else:
                st.info(f"Durum: {existing_f[0]['status']}")
            st.divider()
        else:
          st.warning("Kullanıcı bulunamadı.")
      except Exception:
        st.warning("Arama sırasında hata oluştu.")


# 9. TAKİP İSTEKLERİ
with tab_istek:
  st.title("Gelen Takip İstekleri")
  reqs = []
  if supabase:
    try:
      reqs = (
          supabase.table("follows")
          .select("id, follower")
          .eq("following", st.session_state.username)
          .eq("status", "pending")
          .execute()
          .data
      )
    except Exception:
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
            invalidate_user_caches()
            st.success("İstek kabul edildi!")
            st.rerun()
        with col2:
          if st.button("Reddet", key=f"rej_{r['follower']}"):
            supabase.table("follows").delete().eq("id", r["id"]).execute()
            invalidate_user_caches()
            st.rerun()
        with col3:
          if st.button("Engelle", key=f"blk_{r['follower']}"):
            supabase.table("blocks").insert({
                "blocker": st.session_state.username,
                "blocked": r["follower"],
            }).execute()
            supabase.table("follows").delete().eq("id", r["id"]).execute()
            invalidate_user_caches()
            st.success("Kullanıcı engellendi.")
            st.rerun()
      st.divider()
  else:
    st.info("Bekleyen takip isteğin yok.")


# 10. ARKADAŞLARIM
with tab_arkadas:
  col_head1, col_head2 = st.columns([6, 1])
  with col_head1:
    st.title("Arkadaşlarım ve Listeleri")
  with col_head2:
    if st.button("🔄 Yenile", key="btn_refresh_friends"):
      invalidate_user_caches()
      st.rerun()

  friends = shared_friends_list

  if friends:
    friend_profiles = {f: get_user_profile(f) for f in friends}
    selected_friend = st.selectbox(
        "Bir arkadaş seç ve listelerini incele:",
        friends,
        format_func=lambda x: (
            f"@{x} ({friend_profiles[x].get('full_name', '')})"
        ),
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
      f_unfinished = get_user_lists(selected_friend, "unfinished")

      f_fav_movies = [i for i in f_favs if i["media_type"] == "Film"]
      f_fav_shows = [i for i in f_favs if i["media_type"] == "Dizi"]
      f_fav_actors = [i for i in f_favs if i["media_type"] == "Oyuncu"]

      f_w_movies = [i for i in f_watch if i["media_type"] == "Film"]
      f_w_shows = [i for i in f_watch if i["media_type"] == "Dizi"]

      f_wd_movies = [i for i in f_watched if i["media_type"] == "Film"]
      f_wd_shows = [i for i in f_watched if i["media_type"] == "Dizi"]

      f_half_movies = [i for i in f_unfinished if i["media_type"] == "Film"]
      f_half_shows = [i for i in f_unfinished if i["media_type"] == "Dizi"]

      st.markdown("---")

      def render_media_list(items_sub, list_label_prefix):
        if not items_sub:
          st.info("Bu liste boş.")
          return
        for it in items_sub:
          st.write(f"**{it['title']}**")
          if it.get("poster"):
            st.image(it["poster"], width=80)

          b1, b2, b3, b4 = st.columns([1, 1, 1, 2])
          with b1:
            if st.button(
                "❤️ Favori",
                key=f"ff_fav_{selected_friend}_{list_label_prefix}_{it['title']}",
            ):
              add_to_list("favorites", it)
              st.success("Favorilere eklendi!")
              st.rerun()
          with b2:
            if st.button(
                "📌 İzle",
                key=f"ff_wat_{selected_friend}_{list_label_prefix}_{it['title']}",
            ):
              add_to_list("watchlist", it)
              st.success("İzleneceklere eklendi!")
              st.rerun()
          with b3:
            if st.button(
                "✅ İzledim",
                key=f"ff_wed_{selected_friend}_{list_label_prefix}_{it['title']}",
            ):
              add_to_list("watched", it)
              st.success("İzlenenlere eklendi!")
              st.rerun()
          with b4:
            with st.popover("📤 Paylaş"):
              st.write("Kime gönderilsin?")
              if friends:
                tf = st.selectbox(
                    "Arkadaş",
                    friends,
                    key=f"ff_sh_{selected_friend}_{list_label_prefix}_{it['title']}",
                )
                if st.button(
                    "Gönder",
                    key=f"btn_ff_sh_{selected_friend}_{list_label_prefix}_{it['title']}",
                ):
                  send_media_to_chat(
                      tf,
                      it["title"],
                      it.get("media_type", "Film"),
                  )
              else:
                st.warning("Arkadaşın yok.")
          st.divider()

      with st.expander("❤️ Favori Filmleri"):
        render_media_list(f_fav_movies, "fav_mov")

      with st.expander("❤️ Favori Dizileri"):
        render_media_list(f_fav_shows, "fav_sho")

      with st.expander("❤️ Favori Oyuncuları"):
        if f_fav_actors:
          for it in f_fav_actors:
            st.write(f"**{it['title']}**")
            if it.get("poster"):
              st.image(it["poster"], width=80)
            b1, b2 = st.columns([1, 3])
            with b1:
              if st.button(
                  "❤️ Favori",
                  key=f"ff_a_fav_{selected_friend}_{it['title']}",
              ):
                add_to_list("favorites", it)
                st.success("Favorilere eklendi!")
                st.rerun()
            with b2:
              with st.popover("📤 Paylaş"):
                st.write("Kime gönderilsin?")
                if friends:
                  tf = st.selectbox(
                      "Arkadaş",
                      friends,
                      key=f"ff_act_{selected_friend}_{it['title']}",
                  )
                  if st.button(
                      "Gönder",
                      key=f"btn_ff_act_{selected_friend}_{it['title']}",
                  ):
                    send_media_to_chat(tf, it["title"], "Oyuncu")
                else:
                  st.warning("Arkadaşın yok.")
            st.divider()
        else:
          st.info("Bu liste boş.")

      with st.expander("📌 İzleyeceği Filmler"):
        render_media_list(f_w_movies, "watch_mov")

      with st.expander("📌 İzleyeceği Diziler"):
        render_media_list(f_w_shows, "watch_sho")

      with st.expander("✅ İzlediği Filmler"):
        render_media_list(f_wd_movies, "watched_mov")

      with st.expander("✅ İzlediği Diziler"):
        render_media_list(f_wd_shows, "watched_sho")

      with st.expander("⏳ Yarıda Kalan Filmleri"):
        render_media_list(f_half_movies, "half_mov")

      with st.expander("⏳ Yarıda Kalan Dizileri"):
        render_media_list(f_half_shows, "half_sho")

  else:
    st.info("Henüz ekli bir arkadaşın yok.")


# 11. SOHBET ODASI
with tab_sohbet:
  st.title("Sohbet Odası")

  friends = shared_friends_list

  if friends:
    friend_profiles = {f: get_user_profile(f) for f in friends}
    chat_partner = st.selectbox(
        "Sohbet edilecek arkadaşı seç:",
        friends,
        format_func=lambda x: f"@{x} ({friend_profiles[x].get('full_name', '')})",
        key="chat_partner_box",
    )
    if chat_partner:
      msgs = _cached_chat_messages(st.session_state.username, chat_partner)

      chat_container = st.container(height=400)
      with chat_container:
        if msgs:
          for m in msgs:
            sender_name = (
                "Sen"
                if m["sender"] == st.session_state.username
                else f"@{m['sender']}"
            )
            raw_time = m.get("created_at", "")
            formatted_time = ""
            if raw_time:
              try:
                clean_time = raw_time.replace("Z", "").split("+")[0]
                dt_obj = datetime.fromisoformat(clean_time) + timedelta(hours=3)
                formatted_time = dt_obj.strftime("%d.%m.%Y %H:%M")
              except Exception:
                formatted_time = raw_time[:16].replace("T", " ")

            col_msg, col_time = st.columns([7, 3])
            with col_msg:
              st.markdown(f"**{sender_name}:** {m['message']}")
            with col_time:
              st.markdown(
                  f"<div style='text-align: right; color: gray; font-size: 0.85em;'>{formatted_time}</div>",
                  unsafe_allow_html=True,
              )

      with st.form(key="chat_form", clear_on_submit=True):
        new_msg = st.text_input("Mesaj yaz...")
        submitted_chat = st.form_submit_button("Gönder")
        if submitted_chat and new_msg:
          if supabase:
            try:
              supabase.table("chats").insert({
                  "sender": st.session_state.username,
                  "receiver": chat_partner,
                  "message": new_msg,
              }).execute()
              _cached_chat_messages.clear()
              st.rerun()
            except Exception as e:
              st.error(f"Mesaj gönderilemedi: {e}")
  else:
    st.info("Sohbet edebileceğin arkadaşın yok.")


# --- 12. KIO AI ---
with tab_kio:
  st.title("🤖 KIO AI Asistan")
  st.write(
      "Film ve diziler hakkında her şeyi sorabilir, güncel yapımlar hakkında"
      " bilgi alabilirsin!"
  )

  if "kio_messages" not in st.session_state:
    st.session_state.kio_messages = [{
        "role": "assistant",
        "content": (
            "Merhaba! Ben KIO. Film, dizi ve sinema dünyası hakkında ne"
            " istersen sorabilirsin."
        ),
    }]

  for msg in st.session_state.kio_messages:
    with st.chat_message(msg["role"]):
      st.markdown(msg["content"])

  if prompt := st.chat_input("KIO'ya bir şeyler sor..."):
    st.session_state.kio_messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
      st.markdown(prompt)

    with st.chat_message("assistant"):
      with st.spinner("Güncel veriler taranıyor..."):
        search_results_text = ""
        try:
          with DDGS() as ddgs:
            results = [r for r in ddgs.text(prompt, max_results=5)]
            if results:
              search_results_text = (
                  "\n\nİNTERNETTEN BULUNAN GÜNCEL BİLGİLER (ÖNCELİKLİ KULLAN):"
              )
              for r in results:
                search_results_text += (
                    f"\n- Başlık: {r.get('title')}\n  İçerik:"
                    f" {r.get('body')}\n  Kaynak: {r.get('href')}"
                )
        except Exception:
          search_results_text = ""

        try:
          client = OpenAI(
              api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1"
          )
          system_prompt = (
              "Ben TVKi platformunun yapay zeka asistanı KIO. Film, dizi"
              " ve sinema konularında uzmansın.\n"
              "Kullanıcının sorusunu yanıtlarken AŞAĞIDAKİ GÜNCEL BİLGİLERİ"
              " mutlaka baz al. Eğer güncel bilgiler verilmişse, eski"
              " bilgilerini bir kenara bırakıp bu güncel verilere göre net ve"
              " doğru cevap ver."
              f"{search_results_text}"
          )

          messages = [{"role": "system", "content": system_prompt}]
          for m in st.session_state.kio_messages:
            messages.append({"role": m["role"], "content": m["content"]})

          completion = client.chat.completions.create(
              model="openai/gpt-oss-120b",
              messages=messages,
              temperature=0.3,
          )
          response_text = completion.choices[0].message.content
        except Exception as e:
          response_text = f"Bağlantı sırasında bir hata oluştu: {e}"

        st.markdown(response_text)
        st.session_state.kio_messages.append(
            {"role": "assistant", "content": response_text}
        )