# DDREC License Server Preparation

This guide targets Alibaba Cloud Linux 3 on x86_64. Run commands as `root` or through an approved root shell.

## Required software

The server must already provide Docker Engine, Docker Compose v2, Nginx, firewalld, OpenSSL, rsync, curl, tar, gzip and sha256sum. The deployment does not require host PostgreSQL, Caddy, Node.js, npm, Python dependencies or an Alibaba Cloud ACR client.

Create the production directories:

```bash
install -d -m 750 /opt/ddrec-license \
  /opt/ddrec-license/release \
  /opt/ddrec-license/backups \
  /opt/ddrec-license/scripts
install -d -m 700 /opt/ddrec-license/config \
  /opt/ddrec-license/secrets
install -d -m 755 /var/www/ddrec-license/admin \
  /var/www/certbot
```

Production files are stored at:

- Configuration: `/opt/ddrec-license/config/.env.production`
- Private signing key: `/opt/ddrec-license/secrets/production_ed25519_private.pem`
- Public signing key: `/opt/ddrec-license/secrets/production_ed25519_public.pem`
- Release versions: `/opt/ddrec-license/release/<version>`
- Current release link: `/opt/ddrec-license/current`
- Database backups: `/opt/ddrec-license/backups`
- Admin static files: `/var/www/ddrec-license/admin`

The private signing key must be owned by `root`, assigned to group `10001`, and use mode `640`:

```bash
chown root:10001 /opt/ddrec-license/secrets/production_ed25519_private.pem
chmod 640 /opt/ddrec-license/secrets/production_ed25519_private.pem
```

This permits only root and the license API runtime group to read the bind-mounted key. Never use mode `644`. The API container continues to run as `10001:10001`, and the Compose mount remains read-only.

## Network preparation

The Alibaba Cloud security group should expose only the restricted SSH management port, TCP 80 and TCP 443. Do not expose TCP 5432 or TCP 8080. In firewalld, allow only the required `ssh`, `http` and `https` services.

Create an A record with host `license` pointing to the ECS public IPv4 address. Do not use the private address `172.19.22.164`. Confirm whether ICP filing is required for the selected region and domain before public service.

Certbot must be run only after:

1. `license.aixcc.top` resolves to the ECS public IPv4 address.
2. Port 80 is reachable from the public Internet.
3. The supplied HTTP Nginx configuration passes `nginx -t` and serves `/admin/` and `/api/v1/health/live`.

The installation script never modifies cloud security groups and never opens 5432 or 8080.
