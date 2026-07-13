# LandGroup safe cPanel deployment

The SQLite database, uploaded media, generated static files, environment secrets, logs, virtual environment, and Passenger restart file are excluded from Git. Never use `git clean`, `git reset --hard`, `flush`, or copy a development database over production.

## Initial development push

```bash
git init
git add .
git commit -m "LandGroup safe deployment baseline"
git branch -M main
git remote add origin YOUR_REMOTE_GIT_URL
git push -u origin main
```

## First cPanel Git setup

From the parent directory of the application (use your actual repository URL/path):

```bash
git clone YOUR_REMOTE_GIT_URL landgroupug.org
cd landgroupug.org
cp .env.example .env
chmod 600 .env
```

Fill `.env` with production values. If cPanel does not automatically load `.env`, export the variables in the cPanel Application Environment Variables screen or in the activation script before Passenger starts.

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

Before the first migration, make an out-of-tree server backup without adding it to Git:

```bash
cp db.sqlite3 "$HOME/landgroup-db-$(date +%Y%m%d-%H%M%S).sqlite3"
```

After deployment, sign in as Treasurer, verify Group Settings (week-one date and weekly contribution), open Manage Deposits, and test a small pending submission through approval.
