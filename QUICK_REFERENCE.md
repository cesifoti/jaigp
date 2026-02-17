# JAIGP Quick Reference Card

## 🚀 System Overview

**Architecture:** 3 Load-Balanced Instances + PostgreSQL + Redis
**Capacity:** 2,000-10,000 concurrent users
**Status:** Production-ready, viral-launch ready

---

## 🔧 Common Commands

### Check System Status
```bash
# All instances
sudo systemctl status jaip@8002 jaip@8003 jaip@8004

# PostgreSQL
sudo systemctl status postgresql

# Redis
sudo systemctl status redis-server

# Nginx
sudo systemctl status nginx
```

### Restart Application

**Zero-Downtime Restart** (recommended):
```bash
sudo systemctl restart jaip@8002 && sleep 5
sudo systemctl restart jaip@8003 && sleep 5
sudo systemctl restart jaip@8004
```

**Fast Restart** (brief downtime):
```bash
sudo systemctl restart jaip@8002 jaip@8003 jaip@8004
```

### View Logs
```bash
# All instances (live)
sudo journalctl -u jaip@8002 -u jaip@8003 -u jaip@8004 -f

# Specific instance
sudo journalctl -u jaip@8002 -f

# Last 100 lines
sudo journalctl -u jaip@8002 -n 100

# Nginx access log
sudo tail -f /var/log/nginx/jaip_access.log

# Nginx error log
sudo tail -f /var/log/nginx/jaip_error.log
```

### Health Checks
```bash
# Check each instance
curl http://127.0.0.1:8002/health
curl http://127.0.0.1:8003/health
curl http://127.0.0.1:8004/health

# Check load balancer
curl https://jaigp.org/health

# Check homepage
curl -s -o /dev/null -w "%{http_code}\n" https://jaigp.org/
```

---

## 📊 Monitoring

### Database Connections
```bash
# Current connections
sudo -u postgres psql -d jaigp -c "SELECT count(*) FROM pg_stat_activity WHERE datname='jaigp';"

# Active queries
sudo -u postgres psql -d jaigp -c "SELECT pid, query FROM pg_stat_activity WHERE datname='jaigp' AND state='active';"
```

### Redis Sessions
```bash
# Session count
redis-cli keys "session:*" | wc -l

# Redis memory
redis-cli info memory | grep used_memory_human

# Redis stats
redis-cli info stats
```

### Request Distribution
```bash
# Requests per instance (last hour)
for port in 8002 8003 8004; do
    count=$(sudo journalctl -u jaip@$port --since "1 hour ago" | grep "GET" | wc -l)
    echo "Port $port: $count requests"
done
```

---

## 🔄 Deployment Workflow

### After Code Changes

1. **Test locally** (if possible)
2. **Backup database** (if schema changes)
   ```bash
   sudo -u postgres pg_dump jaigp > /tmp/backup_$(date +%Y%m%d).sql
   ```
3. **Pull/update code**
   ```bash
   cd /var/www/ai_journal
   git pull  # or copy files
   ```
4. **Update dependencies** (if requirements.txt changed)
   ```bash
   source venv/bin/activate
   pip install -r requirements.txt
   ```
5. **Zero-downtime restart**
   ```bash
   sudo systemctl restart jaip@8002 && sleep 5
   sudo systemctl restart jaip@8003 && sleep 5
   sudo systemctl restart jaip@8004
   ```
6. **Verify**
   ```bash
   curl https://jaigp.org/health
   ```

---

## 🆘 Troubleshooting

### Instance Won't Start
```bash
# Check logs
sudo journalctl -u jaip@8002 -n 50

# Check port in use
sudo lsof -i :8002

# Test manually
cd /var/www/ai_journal
source venv/bin/activate
uvicorn main:app --host 127.0.0.1 --port 8002
```

### Database Connection Issues
```bash
# Check PostgreSQL is running
sudo systemctl status postgresql

# Check connections
sudo -u postgres psql -d jaigp -c "SELECT count(*) FROM pg_stat_activity;"

# Kill idle connections
sudo -u postgres psql -d jaigp -c "
  SELECT pg_terminate_backend(pid)
  FROM pg_stat_activity
  WHERE state = 'idle' AND state_change < now() - interval '30 minutes';
"
```

### Redis Connection Issues
```bash
# Check Redis is running
sudo systemctl status redis-server

# Test connection
redis-cli ping

# Restart Redis
sudo systemctl restart redis-server
```

### Load Balancer Issues
```bash
# Test nginx configuration
sudo nginx -t

# Reload nginx
sudo systemctl reload nginx

# Check nginx logs
sudo tail -f /var/log/nginx/jaip_error.log
```

### Site is Slow
```bash
# Check database slow queries
sudo -u postgres psql -d jaigp -c "
  SELECT pid, now() - query_start as duration, query
  FROM pg_stat_activity
  WHERE state != 'idle'
  ORDER BY duration DESC
  LIMIT 10;
"

# Check Redis memory
redis-cli info memory

# Check system resources
htop
free -h
df -h
```

---

## 📈 Scaling Up

### Add 4th Instance
```bash
# Start new instance
sudo systemctl start jaip@8005
sudo systemctl enable jaip@8005

# Add to nginx
sudo nano /etc/nginx/sites-available/jaip
# Add: server 127.0.0.1:8005 max_fails=3 fail_timeout=30s;

# Reload nginx
sudo nginx -t
sudo systemctl reload nginx
```

### Remove Instance
```bash
# Remove from nginx first
sudo nano /etc/nginx/sites-available/jaip
# Remove the server line

# Reload nginx
sudo systemctl reload nginx

# Stop instance
sudo systemctl stop jaip@8002
sudo systemctl disable jaip@8002
```

---

## 🔒 Security Checks

```bash
# Check for updates
sudo apt update
sudo apt list --upgradable

# Check SSL certificate expiry
sudo certbot certificates

# Review nginx security headers
curl -I https://jaigp.org/

# Check rate limiting
for i in {1..10}; do
    curl -I https://jaigp.org/ 2>&1 | grep -i ratelimit
done
```

---

## 💾 Backups

### Database Backup
```bash
# Create backup
sudo -u postgres pg_dump jaigp > /tmp/jaigp_backup_$(date +%Y%m%d_%H%M%S).sql

# Restore backup
sudo -u postgres psql jaigp < /tmp/jaigp_backup_20260214.sql
```

### Redis Backup
```bash
# Save immediately
redis-cli SAVE

# Backup file location
sudo cp /var/lib/redis/dump.rdb /tmp/redis_backup_$(date +%Y%m%d).rdb
```

### Configuration Backup
```bash
# Backup configs
sudo tar -czf /tmp/jaigp_configs_$(date +%Y%m%d).tar.gz \
  /etc/systemd/system/jaip@.service \
  /etc/nginx/sites-available/jaip \
  /var/www/ai_journal/.env
```

---

## 📞 Quick Diagnostics

**Run this to check everything at once:**
```bash
bash /tmp/final_verification.sh
```

Or manually:
```bash
echo "Instances:"; systemctl is-active jaip@8002 jaip@8003 jaip@8004
echo "PostgreSQL:"; systemctl is-active postgresql
echo "Redis:"; systemctl is-active redis-server
echo "Nginx:"; systemctl is-active nginx
echo "DB Connections:"; sudo -u postgres psql -d jaigp -t -c "SELECT count(*) FROM pg_stat_activity WHERE datname='jaigp';" | xargs
echo "Redis Sessions:"; redis-cli keys "session:*" | wc -l
echo "Health Check:"; curl -s https://jaigp.org/health
```

---

## 📚 Documentation

- **Full Scalability Guide:** `SCALABILITY_IMPLEMENTATION.md`
- **Load Balancing Details:** `LOAD_BALANCING_SETUP.md`
- **This Reference:** `QUICK_REFERENCE.md`

---

## 🎯 Key Metrics

**Normal Operation:**
- CPU Usage: 5-20%
- Memory Usage: 600-900MB
- DB Connections: 4-10 (max 60)
- Response Time: 40-100ms
- All instances: active/healthy

**Alerts Needed If:**
- Any instance down for >5 minutes
- DB connections >50
- Response time >500ms
- Disk usage >80%
- Memory usage >90%

---

**Last Updated:** February 14, 2026
**System Version:** 3.0 (Load Balanced)
