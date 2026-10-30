# To-Do List on AWS

Flask app + PostgreSQL (Amazon RDS), running in Docker on an Amazon Linux 2023 EC2 instance.

## Architecture
```mermaid
flowchart LR
  U[Browser] -->|HTTP :80| D
  subgraph AWS["AWS default VPC"]
    subgraph EC2["EC2 t3.micro, Amazon Linux 2023 - SG todo-web-sg: port 80 open"]
      D["Docker: gunicorn + Flask :8000"]
      A[SSM agent]
    end
    D -->|"5432, SG-to-SG only"| RDS[("RDS PostgreSQL db.t3.micro, private")]
    SSM[AWS Systems Manager]
  end
  Dev[Developer] -->|git push| GH[GitHub repo]
  GH --> CI["Actions: CI build + test"]
  CI -->|on success| DEP["Actions: Deploy"]
  DEP -->|"IAM user keys: SendCommand"| SSM
  SSM --> A
  A -->|"git pull, docker build, docker run"| D
  A -.->|"git pull over HTTPS"| GH
  Dev -.->|Session Manager shell| SSM
```
Request path: browser -> EC2 public IP:80 -> Docker port map -> gunicorn/Flask -> RDS -> response back the same way.

Deploy path (separate from user traffic): git push -> GitHub Actions CI -> Deploy workflow -> AWS Systems Manager -> SSM agent on EC2 -> git pull + docker rebuild. No SSH port is needed.

## Run locally
    docker compose up --build   # http://localhost:8000

## Deploy to AWS
1. **Billing alert**: Billing > Budgets > create a $1 budget with email alert.
2. **RDS**: PostgreSQL, free-tier template, db.t3.micro, 20 GB, *Public access: No*, new SG `todo-rds-sg`, initial DB `todos`.
3. **EC2**: Amazon Linux 2023, t3.micro (or t2.micro), SG `todo-web-sg`: inbound 80 from 0.0.0.0/0, 22 from *your IP only*. Attach an IAM instance profile with the `AmazonSSMManagedInstanceCore` policy (needed for auto-deploy).
4. **RDS SG**: inbound 5432 with source = `todo-web-sg` (not a CIDR).
5. SSH in and install Docker:

       sudo dnf install -y docker git
       sudo systemctl enable --now docker
       sudo usermod -aG docker ec2-user && newgrp docker

6. Clone, create `.env` on the server (never committed), run:

       git clone https://github.com/AHLegendary/EC2DOList.git app && cd app
       cp .env.example .env && nano .env      # fill in RDS endpoint + password
       docker build -t todo .
       docker run -d --name todo --restart unless-stopped -p 80:8000 --env-file .env todo

7. Open `http://<ec2-public-ip>/` and `/health`.

## Environment variables
The app reads its database settings from the environment. Nothing is hardcoded.

| Variable | Required | Default | Meaning |
|---|---|---|---|
| `DB_HOST` | yes | - | Database hostname (`db` in compose, RDS endpoint on EC2) |
| `DB_USER` | yes | - | Database user |
| `DB_PASSWORD` | yes | - | Database password |
| `DB_NAME` | no | `todos` | Database name |
| `DB_PORT` | no | `5432` | Database port |

Where they come from: `docker-compose.yml` locally and in CI, and a `.env` file on the EC2 server (never committed; see `.env.example`).

GitHub settings used by the deploy workflow (Settings > Secrets and variables > Actions):

| Where | Name | Example |
|---|---|---|
| Variables tab | `AWS_REGION` | `us-east-2` |
| Variables tab | `EC2_INSTANCE_ID` | `i-0abc123def4567890` |
| Secrets tab | `AWS_ACCESS_KEY_ID` | from the `github-deploy` IAM user |
| Secrets tab | `AWS_SECRET_ACCESS_KEY` | from the `github-deploy` IAM user |

## Redeploy
Automatic via the Deploy workflow. To do it by hand:

    git pull && docker build -t todo . && docker rm -f todo && docker run -d --name todo --restart unless-stopped -p 80:8000 --env-file .env todo

## Auto-deploy (GitHub Actions + SSM)
`.github/workflows/deploy.yml` runs after CI passes on `main`. It signs in to AWS as a limited IAM user and uses AWS Systems Manager to run the redeploy on the instance, so port 22 stays closed to the internet. Until `EC2_INSTANCE_ID` is set, the job skips.

One-time setup:
1. IAM > Policies > Create policy > JSON tab. Name it `todo-ssm-deploy` (replace the placeholders):

       {
         "Version": "2012-10-17",
         "Statement": [
           {"Effect": "Allow", "Action": "ssm:SendCommand",
            "Resource": [
              "arn:aws:ec2:<REGION>:<ACCOUNT_ID>:instance/<INSTANCE_ID>",
              "arn:aws:ssm:<REGION>::document/AWS-RunShellScript"]},
           {"Effect": "Allow",
            "Action": ["ssm:GetCommandInvocation", "ssm:ListCommandInvocations"],
            "Resource": "*"}
         ]
       }

2. IAM > Users > Create user `github-deploy` (no console access), attach `todo-ssm-deploy` directly.
3. Open the user > Security credentials > Create access key > "Application running outside AWS". Copy both values.
4. In GitHub, add the two secrets and two variables from the table above.
5. Actions tab > Deploy > Run workflow to test it.

The server clones over HTTPS, so the repo must be public (or use a deploy key) for `git pull` to work.

**Tradeoff:** access keys are long-lived credentials. I used them because my AWS account plan would not let me create the IAM identity provider that GitHub OIDC needs. The user can only send commands to this one instance. With OIDC, GitHub would get short-lived credentials and no keys would be stored at all, which is what I'd switch to for production.

## Why is the frontend inside `app.py`?
A browser can't talk to a database directly (Postgres isn't meant to be exposed to the internet), so there are always three pieces:

    Browser (HTML) -> Server code (app.py) -> Database (Postgres)

`app.py` is the middle piece. It also serves the HTML page (the `PAGE` string), so the whole app is one container with no build step. I chose that because this assignment is about deployment, not app complexity.

The alternative is a separate React frontend calling a JSON API in Flask. It works, but adds a build step and a second thing to serve and explain, so I skipped it. It would be a natural next step if the app grew.

## CI
`.github/workflows/ci.yml` runs on every push to `main` and on pull requests. It builds the Docker image, starts the app with a test Postgres, waits for `/health`, then adds a to-do and reads it back. A failing check means a broken build never reaches the server, because the Deploy workflow only runs after CI succeeds.

## Nice-to-haves I chose, and why
- **Docker.** The same image runs on my laptop, in CI, and on EC2, so "works on my machine" problems mostly disappear. The server only needs Docker, not a Python setup, and `--restart unless-stopped` brings the app back after a crash or reboot. *Considered:* running Python directly under systemd. It's simpler, but the server can drift from what I tested locally.
- **CI/CD with GitHub Actions.** CI builds the image and smoke-tests every push: `/health` must pass and a to-do must be written to and read back from the database. The Deploy workflow runs only after CI passes and redeploys through Systems Manager, so nobody has to log in to ship a change. I chose GitHub Actions because the code is already on GitHub and there is no extra service to run. *Considered:* Jenkins or CodePipeline, which need more setup and may cost money.

**Not chosen, and what I'd do next:**
- **Terraform:** would make the whole setup repeatable. I clicked through the console to focus on a working deployment first.
- **HTTPS:** needs a domain and a load balancer or CloudFront. It's the first thing I'd add before real users.
- **Monitoring and alerts:** I'd add CloudWatch alarms or an uptime check on `/health`.

## Design choices / tradeoffs
- **EC2 + Docker, no Lambda**: the assignment requires EC2; Lambda would add API Gateway + VPC networking with no benefit here.
- **RDS over self-hosted DB**: managed backups/patching; tradeoff is free-tier limits and cost after it.
- **Amazon Linux 2023**: AWS-maintained, SSM-ready; considered Ubuntu (more familiar, similar).
- **Security**: no secrets in repo, RDS not public, SG-to-SG rule, SSH limited to my IP.
- **Before real customers**: HTTPS (ALB + ACM), Multi-AZ RDS, Secrets Manager, CI/CD, CloudWatch alarms, private subnets.
