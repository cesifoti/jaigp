# JAIP Quick Start Guide

Get JAIP running in 5 minutes!

## Prerequisites

- Python 3.12+
- ORCID account (for testing OAuth)

## Step 1: Setup (First Time Only)

```bash
# Navigate to project
cd /var/www/ai_journal

# Activate virtual environment (already created)
source venv/bin/activate

# Verify dependencies are installed
pip list | grep fastapi
```

## Step 2: Configure ORCID (Optional for Testing)

For full functionality, you need ORCID credentials:

1. Go to https://orcid.org/developer-tools
2. Sign in with your ORCID account
3. Click "Register for the free ORCID public API"
4. Fill in the form:
   - **Name**: JAIP Development
   - **Website**: http://localhost:8002
   - **Description**: Testing JAIP locally
   - **Redirect URI**: `http://localhost:8002/auth/callback`
5. Submit and copy your Client ID and Client Secret
6. Update `.env`:
   ```bash
   ORCID_CLIENT_ID=your-client-id
   ORCID_CLIENT_SECRET=your-client-secret
   ```

> **Note**: Without ORCID credentials, you can still view the app but cannot login or submit papers.

## Step 3: Run the Application

**Option 1 - Easy way (recommended):**
```bash
./run.sh
```

**Option 2 - Manual way:**
```bash
# Activate virtual environment
source venv/bin/activate

# Run the application
python main.py
```

**Option 3 - One-liner:**
```bash
source venv/bin/activate && python main.py
```

You should see:
```
✓ Database initialized
✓ JAIP - Journal for AI Generated Papers starting on 127.0.0.1:8002
INFO:     Uvicorn running on http://127.0.0.1:8002
```

## Step 4: Access the Application

Open your browser and go to:
**http://localhost:8002**

## What You Can Do

### Without ORCID Login:
- ✅ View homepage
- ✅ Read about page
- ✅ Browse issues (once papers are added)
- ✅ View paper details
- ✅ Read comments

### With ORCID Login:
- ✅ All of the above, plus:
- ✅ Submit papers
- ✅ Upload PDFs and images
- ✅ Add AI co-authors
- ✅ Post comments
- ✅ Vote on comments
- ✅ Submit new versions
- ✅ View your profile

## Testing the Application

### 1. Test Homepage
```
http://localhost:8002/
```
Should show the homepage with hero section.

### 2. Test About Page
```
http://localhost:8002/about
```
Should show information about JAIP.

### 3. Test Issues Navigation
```
http://localhost:8002/issues
```
Should show year navigation (empty until papers are added).

### 4. Test ORCID Login (if configured)
```
http://localhost:8002/auth/login
```
Should redirect to ORCID for authentication.

## Common Issues

### Port Already in Use
```bash
# Check if port 8002 is in use
sudo netstat -tlnp | grep 8002

# Kill the process if needed
sudo kill <PID>
```

### Database Errors
```bash
# Reinitialize database
rm data/jaip.db
python -c "from models.database import init_db; init_db()"
```

### ORCID Redirect Error
Make sure your redirect URI in ORCID settings exactly matches:
```
http://localhost:8002/auth/callback
```

### Module Not Found
```bash
# Reinstall dependencies
source venv/bin/activate
pip install -r requirements.txt
```

## Stop the Application

Press `Ctrl+C` in the terminal where the application is running.

## Directory Structure Quick Reference

```
/var/www/ai_journal/
├── main.py           # Start here - main application
├── config.py         # Configuration settings
├── .env              # Environment variables (SECRET!)
├── models/           # Database models
├── routes/           # API endpoints
├── services/         # Business logic
├── templates/        # HTML templates
├── static/           # CSS, JS, images
└── data/            # Database and uploaded files
```

## Next Steps

1. **Get ORCID Credentials** (if you haven't already)
2. **Submit a Test Paper** to see the full workflow
3. **Explore the Code** - well-documented and organized
4. **Read DEPLOYMENT.md** when ready for production
5. **Customize** - modify templates and styling as needed

## Quick Commands Reference

```bash
# Start application
python main.py

# Run in background
python main.py &

# Check if running
ps aux | grep python

# View logs (if running as service)
sudo journalctl -u jaip -f

# Backup database
cp data/jaip.db data/jaip_backup_$(date +%Y%m%d).db
```

## Support

- **Documentation**: See README.md for detailed docs
- **Deployment**: See DEPLOYMENT.md for production setup
- **Implementation**: See IMPLEMENTATION_SUMMARY.md for technical details

## Development Tips

### Hot Reload
The app automatically reloads when you change Python files (DEBUG=True).

### Database Changes
After changing models:
```bash
python -c "from models.database import init_db; init_db()"
```

### Template Changes
Templates reload automatically - just refresh your browser.

### Static File Changes
CSS/JS changes may need a hard refresh: `Ctrl+Shift+R`

## Security Reminder

⚠️ **Never commit .env to git** - it contains secrets!

The .env file is already in .gitignore, but always verify:
```bash
git status
# .env should NOT appear in the list
```

---

**You're all set!** Visit http://localhost:8002 to see your JAIP installation.

*"We are not sure if these papers are good, after all, we are only human."*
