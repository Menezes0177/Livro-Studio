# LivroStudio V3.5

Atualização visual e de descoberta de livros.

## Novidades
- Modo claro e modo escuro com preferência salva.
- Seletor de wallpaper/GIF pela tela Aparência.
- Três wallpapers 60 FPS adicionais em `assets/`.
- Pesquisa na Biblioteca e no Explorer.
- Novo hover/parallax muito mais suave na Biblioteca.
- Scrollbars modernas em áreas de rolagem.
- Explorer local com capas, título, autor, sinopse e ações Ler/+ Biblioteca.
- Campo de autor, sinopse e visibilidade ao criar um livro.
- Banco SQLite com migração automática das colunas novas.

## Observação sobre o online
A V3.5 deixa o modelo de dados e a interface preparados para o Explorer, mas a publicação entre computadores ainda precisa de um backend online (contas, API, armazenamento e banco remoto). Sem uma conta/projeto de backend, não é possível hospedar uma base compartilhada de forma real a partir do aplicativo sozinho.

## Build
```powershell
python -m pip install -r requirements.txt
python -m PyInstaller --noconfirm --clean --windowed --onedir --name LivroStudio --icon "livrostudio.ico" --add-data "livrostudio.ico;." --add-data "style.qss;." --add-data "theme_dark.qss;." --add-data "theme_light.qss;." --add-data "assets;assets" main.py
```

## Online real
Veja `README_ONLINE.md` e `online_schema.sql` para configurar o Explorer entre computadores usando Supabase.
