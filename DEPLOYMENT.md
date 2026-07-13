# LandGroup safe cPanel deployment

The SQLite database, uploaded media, generated static files, environment secrets, logs, virtual environment, and Passenger restart file are excluded from Git. Never use `git clean`, `git reset --hard`, `flush`, or copy a development database over production.

## Initial development push

```bash
git init
git add .
git commit -m "LandGroup safe deployment baseline"
git branch -M main
git remote add origin https://github.com/MarcDemo/LandGroup.git
git push -u origin main
```

## One-time setup for the existing cPanel application

Back up the production database outside the application, then attach the existing application directory to Git. The checkout replaces source code only; `db.sqlite3`, `.env`, `media/`, generated static files, logs, and Passenger temporary files do not exist in the Git tree and remain in place.

```bash
cd /home/farmsnva/landgroupug.org
cp db.sqlite3 "$HOME/landgroup-db-$(date +%Y%m%d-%H%M%S).sqlite3"
git init
git remote add origin https://github.com/MarcDemo/LandGroup.git
git fetch origin
git checkout -f -B main origin/main
test -f .env || cp .env.example .env
chmod 600 .env
```

Use the absolute application path, normally `/home/farmsnva/landgroupug.org`. Fill `.env` with production values; this project loads that file directly at startup.

## Every future deployment

Run these commands from the existing production application directory. The database and media directory remain untouched because they are not tracked:

```bash
cd /home/farmsnva/landgroupug.org
git status --short
git pull --ff-only origin main
source /home/farmsnva/virtualenv/landgroupug.org/3.11/bin/activate
python -m pip install -r requirements.txt
python manage.py check --deploy
python manage.py migrate --noinput
python manage.py collectstatic --noinput
mkdir -p tmp
touch tmp/restart.txt
```

Replace the virtual-environment path/version with the exact value shown by cPanel’s **Setup Python App** page. If cPanel provides a **Restart** button, it can be used instead of `touch tmp/restart.txt`.

Before every important migration, an optional timestamped out-of-tree backup can be made without adding it to Git:

```bash
cp db.sqlite3 "$HOME/landgroup-db-$(date +%Y%m%d-%H%M%S).sqlite3"
```

After deployment, sign in as Treasurer, verify Group Settings (week-one date and weekly contribution), open Manage Deposits, and test a small pending submission through approval.
