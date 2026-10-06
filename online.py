import json
import uuid
import urllib.request
import sys
from pathlib import Path
from datetime import datetime

try:
    from supabase import create_client, Client
except ImportError:
    create_client = None
    Client = object


class OnlineConfigError(RuntimeError):
    pass


class OnlineAuthError(RuntimeError):
    pass


class OnlineService:
    """Cliente online do LivroStudio usando Supabase + RLS."""

    def __init__(self, config_path: Path, session_path: Path):
        self.config_path = Path(config_path)
        self.session_path = Path(session_path)
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.url = ""
        self.key = ""
        self.client = None
        # Configuração embutida no aplicativo (publicável, sem secrets).
        # Em desenvolvimento fica ao lado dos arquivos do projeto;
        # no PyInstaller fica dentro dos recursos empacotados.
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            self.bundled_config_path = Path(sys._MEIPASS) / "supabase_config.json"
        else:
            self.bundled_config_path = Path(__file__).resolve().parent / "supabase_config.json"
        self._load_config()
        if self.configured:
            self._connect()
            self._restore_session()

    @property
    def configured(self):
        return bool(self.url and self.key and create_client is not None)

    def _load_config(self):
        # Preferência: configuração local do usuário.
        # Fallback: configuração embutida na distribuição oficial.
        candidates = [self.config_path, self.bundled_config_path]
        for path in candidates:
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                url = str(data.get("url", "")).strip().rstrip("/")
                key = str(data.get("publishable_key", "")).strip()
                if url and key:
                    self.url = url
                    self.key = key
                    return
            except Exception:
                continue
        self.url = ""
        self.key = ""

    def configure(self, url: str, key: str):
        url = url.strip().rstrip("/")
        key = key.strip()
        if not url.startswith("https://") or "supabase.co" not in url:
            raise OnlineConfigError("O Project URL do Supabase parece inválido.")
        if not key:
            raise OnlineConfigError("Informe a Publishable Key do projeto.")
        if create_client is None:
            raise OnlineConfigError("A biblioteca 'supabase' não está instalada. Rode: python -m pip install supabase")
        self.url = url
        self.key = key
        self.config_path.write_text(
            json.dumps({"url": url, "publishable_key": key}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._connect()

    def _connect(self):
        if create_client is None:
            return
        self.client = create_client(self.url, self.key)

    def _save_session(self, session):
        if not session:
            return
        data = {
            "access_token": getattr(session, "access_token", ""),
            "refresh_token": getattr(session, "refresh_token", ""),
        }
        if data["access_token"] and data["refresh_token"]:
            self.session_path.write_text(json.dumps(data), encoding="utf-8")

    def _restore_session(self):
        if not self.client or not self.session_path.exists():
            return
        try:
            data = json.loads(self.session_path.read_text(encoding="utf-8"))
            if data.get("access_token") and data.get("refresh_token"):
                result = self.client.auth.set_session(data["access_token"], data["refresh_token"])
                self._save_session(getattr(result, "session", None))
        except Exception:
            try:
                self.session_path.unlink(missing_ok=True)
            except Exception:
                pass

    def current_user(self):
        if not self.client:
            return None
        try:
            response = self.client.auth.get_user()
            return getattr(response, "user", None)
        except Exception:
            return None

    def sign_in(self, email: str, password: str):
        if not self.client:
            raise OnlineConfigError("Configure o projeto online primeiro.")
        if not email or not password:
            raise OnlineAuthError("Digite e-mail e senha.")
        response = self.client.auth.sign_in_with_password({"email": email, "password": password})
        session = getattr(response, "session", None)
        if not session:
            raise OnlineAuthError("Não foi possível iniciar a sessão.")
        self._save_session(session)
        self._ensure_profile()
        return response

    def sign_up(self, email: str, password: str, username: str):
        if not self.client:
            raise OnlineConfigError("Configure o projeto online primeiro.")
        if not email or not password or not username:
            raise OnlineAuthError("Preencha e-mail, senha e nome de usuário.")
        if len(password) < 6:
            raise OnlineAuthError("Use uma senha com pelo menos 6 caracteres.")
        response = self.client.auth.sign_up({
            "email": email,
            "password": password,
            "options": {"data": {"username": username}},
        })
        session = getattr(response, "session", None)
        if session:
            self._save_session(session)
            self._ensure_profile(username)
        return {"user": getattr(response, "user", None), "session": session}

    def sign_out(self):
        if self.client:
            self.client.auth.sign_out()
        try:
            self.session_path.unlink(missing_ok=True)
        except Exception:
            pass

    def _ensure_profile(self, username=None):
        user = self.current_user()
        if not user:
            return
        uid = str(user.id)
        if username is None:
            metadata = getattr(user, "user_metadata", {}) or {}
            username = metadata.get("username") or (getattr(user, "email", "user").split("@")[0])
        try:
            self.client.table("profiles").upsert(
                {"id": uid, "username": username},
                on_conflict="id",
            ).execute()
        except Exception:
            pass

    def get_profile(self):
        user = self.current_user()
        if not user:
            return None
        response = self.client.table("profiles").select("id, username").eq("id", str(user.id)).maybe_single().execute()
        profile = response.data or {}
        metadata = getattr(user, "user_metadata", {}) or {}
        profile["avatar_url"] = metadata.get("avatar_url") or ""
        profile["avatar_path"] = metadata.get("avatar_path") or ""
        return profile

    def set_avatar(self, image_path: Path):
        user = self.current_user()
        if not user:
            raise OnlineAuthError("Entre na sua conta antes de escolher uma foto de perfil.")
        image_path = Path(image_path)
        if not image_path.exists():
            raise FileNotFoundError("A imagem de perfil não foi encontrada.")
        suffix = image_path.suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
            raise ValueError("Use uma imagem PNG, JPG ou WEBP.")
        mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}[suffix]
        metadata = dict(getattr(user, "user_metadata", {}) or {})
        old_path = metadata.get("avatar_path") or ""
        path = f"{user.id}/profile_avatar{suffix}"
        with image_path.open("rb") as f:
            self.client.storage.from_("book-covers").upload(
                path=path,
                file=f,
                file_options={"content-type": mime, "upsert": "true"},
            )
        avatar_url = self.client.storage.from_("book-covers").get_public_url(path)
        # Cache-busting: evita que o navegador/Qt mostre a foto anterior.
        avatar_url = f"{avatar_url}?v={uuid.uuid4().hex[:10]}"
        metadata["avatar_url"] = avatar_url
        metadata["avatar_path"] = path
        self.client.auth.update_user({"data": metadata})
        if old_path and old_path != path:
            try:
                self.client.storage.from_("book-covers").remove([old_path])
            except Exception:
                pass
        return avatar_url

    def remove_avatar(self):
        user = self.current_user()
        if not user:
            raise OnlineAuthError("Entre na sua conta antes de remover a foto de perfil.")
        metadata = dict(getattr(user, "user_metadata", {}) or {})
        old_path = metadata.get("avatar_path") or ""
        if old_path:
            try:
                self.client.storage.from_("book-covers").remove([old_path])
            except Exception:
                pass
        metadata["avatar_url"] = ""
        metadata["avatar_path"] = ""
        self.client.auth.update_user({"data": metadata})

    def publish_book(self, title, text, synopsis, author, cover_source: Path):
        user = self.current_user()
        if not user:
            raise OnlineAuthError("Entre na sua conta antes de publicar.")
        cover_source = Path(cover_source)
        if not cover_source.exists():
            raise FileNotFoundError("A capa não foi encontrada.")
        suffix = cover_source.suffix.lower() or ".png"
        path = f"{user.id}/{uuid.uuid4().hex}{suffix}"
        mime = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
        }.get(suffix, "application/octet-stream")
        with cover_source.open("rb") as f:
            self.client.storage.from_("book-covers").upload(
                path=path,
                file=f,
                file_options={"content-type": mime, "upsert": "false"},
            )
        cover_url = self.client.storage.from_("book-covers").get_public_url(path)
        response = self.client.table("books").insert({
            "author_id": str(user.id),
            "author": author or "Autor",
            "title": title,
            "synopsis": synopsis or "",
            "text": text,
            "cover_path": path,
            "cover_url": cover_url,
            "visibility": "public",
        }).execute()
        if not response.data:
            raise RuntimeError("O servidor não retornou o livro publicado.")
        return cover_url

    def public_books(self):
        if not self.client:
            return []
        response = (
            self.client.table("books")
            .select("id, author_id, title, synopsis, author, cover_url, cover_path, created_at")
            .eq("visibility", "public")
            .order("created_at", desc=True)
            .limit(100)
            .execute()
        )
        return response.data or []

    def unpublish_book(self, book_id):
        user = self.current_user()
        if not user:
            raise OnlineAuthError("Entre na sua conta para gerenciar seus livros.")
        response = (
            self.client.table("books")
            .update({"visibility": "private"})
            .eq("id", str(book_id))
            .eq("author_id", str(user.id))
            .execute()
        )
        if not response.data:
            raise RuntimeError("Não foi possível tirar o livro do Explorer. Verifique se você é o criador do livro.")
        return response.data[0]

    def get_public_book(self, book_id):
        if not self.client:
            return None
        response = (
            self.client.table("books")
            .select("id, title, synopsis, author, text, cover_url, cover_path, created_at, visibility")
            .eq("id", str(book_id))
            .eq("visibility", "public")
            .maybe_single()
            .execute()
        )
        return response.data or None

    def add_to_library(self, book_id):
        user = self.current_user()
        if not user:
            raise OnlineAuthError("Entre na sua conta para usar sua biblioteca online.")
        self.client.table("library").upsert(
            {"user_id": str(user.id), "book_id": str(book_id)},
            on_conflict="user_id,book_id",
        ).execute()

    def download_cover(self, url, title):
        if not url:
            raise RuntimeError("Este livro não possui uma capa online.")
        safe = "".join(c if c.isalnum() or c in "-_ " else "_" for c in title).strip()[:80] or "livro"
        destination = self.config_path.parent / "covers" / f"online_{safe}_{uuid.uuid4().hex[:8]}.jpg"
        destination.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(url, destination)
        return destination
