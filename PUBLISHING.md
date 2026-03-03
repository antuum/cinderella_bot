# Publishing Cinderella to GitHub

## 1. Create a GitHub repository

1. Go to [github.com/new](https://github.com/new)
2. Repository name: `cinderella-bot` (or any name you like)
3. Description: `Telegram bot for shared flat cleaning rotation`
4. Choose **Public**
5. **Do not** initialize with README, .gitignore, or license (we already have them)
6. Click **Create repository**

## 2. Push your code

```bash
cd /Users/antuum/WEB/Papialushka_Bot

# Add your GitHub repo as remote (replace YOUR_USERNAME with your GitHub username)
git remote add origin https://github.com/YOUR_USERNAME/cinderella-bot.git

# Push
git push -u origin main
```

If you use SSH:
```bash
git remote add origin git@github.com:YOUR_USERNAME/cinderella-bot.git
git push -u origin main
```

## 3. Update the clone URL in README

Edit `README.md` and replace `antuum` in the clone URL with your actual GitHub username:

```bash
git clone https://github.com/YOUR_USERNAME/cinderella-bot.git
```

Then commit and push:
```bash
git add README.md && git commit -m "Fix clone URL" && git push
```

## 4. Optional: Add repository details on GitHub

- **Topics:** `telegram-bot`, `python`, `cleaning`, `shared-flat`, `automation`
- **Website:** Leave blank or add a demo link
- **About:** Short description for the repo sidebar

## 5. Optional: Add papialushka.png

If you want to include the bot avatar image in the repo:

```bash
git add papialushka.png
git commit -m "Add bot avatar"
git push
```
