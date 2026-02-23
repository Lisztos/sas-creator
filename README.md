# SAS Creator Bot

Automated browser agent for creating an SAS (Sociedad por Acciones Simplificada) company on [tuempresa.gob.mx](https://www.tuempresa.gob.mx/sas/).

The site is notoriously slow and error-prone. This bot automates the login and navigation process, retrying automatically when the site fails, and notifying you via Telegram when progress is made.

## Features

- **Visible browser** - Watch the bot work and take over at any point
- **Auto-retry** - Exponential backoff with configurable intervals (default: 5 min)
- **Telegram notifications** - Get notified on success, failure, or when you need to intervene
- **State persistence** - Survives restarts; picks up where it left off
- **Human take-over** - The bot detects when you've manually advanced and adapts
- **Screenshots on failure** - Every error is captured for debugging

## Setup

### 1. Install Python dependencies

```bash
cd sas-creator
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 2. Install Playwright browsers

```bash
playwright install chromium
```

### 3. Add your e.firma credentials

Create a `credentials/` folder and place your files:

```
credentials/
  your_certificate.cer
  your_private_key.key
```

Update `config.yaml` with the correct file names:

```yaml
credentials:
  cer_path: "./credentials/your_certificate.cer"
  key_path: "./credentials/your_private_key.key"
```

### 4. Set up secrets

Copy the example and fill in your values:

```bash
cp .env.example .env
```

Edit `.env`:

```
SAS_KEY_PASSWORD=your_efirma_password
TELEGRAM_BOT_TOKEN=your_bot_token_here
```

### 5. Set up Telegram notifications

1. Open Telegram and search for **@BotFather**
2. Send `/newbot` and follow the prompts to create your bot
3. Copy the bot token (looks like `123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11`)
4. Start a chat with your new bot (search for it by name and click **Start**)
5. Send any message to your bot (e.g. "hello")
6. Open in your browser: `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
7. Find `"chat":{"id":XXXXXX}` in the response - that number is your `chat_id`
8. Add the token to `.env` as `TELEGRAM_BOT_TOKEN`
9. Add the chat_id to `config.yaml` under `telegram.chat_id`

## Usage

### Run the bot

```bash
source .venv/bin/activate
python -m sas_creator
```

A Chrome window will open. The bot will:

1. Navigate to the SAS portal
2. Upload your `.cer` and `.key` files
3. Enter your password
4. Click "Ingresar"
5. If login fails (site error, timeout), wait 5 minutes and retry
6. Send you a Telegram message on success or failure

### Take over manually

The browser window is always visible. You can:

- Click on things while the bot is waiting between retries
- The bot will detect your progress and skip completed steps
- Press `Ctrl+C` in the terminal to stop the bot (state is saved)

### Reset state

If you need to start over:

```bash
rm -f state/run_state.json
```

### Check logs

```bash
tail -f logs/sas_creator.log
```

## Configuration

All settings are in `config.yaml`. Key options:

| Setting | Default | Description |
|---------|---------|-------------|
| `retry.base_interval_seconds` | 300 | Wait time between retries (5 min) |
| `retry.max_attempts` | 0 | Max retries per step (0 = infinite) |
| `browser.headless` | false | Set to true to run without visible browser |
| `browser.slow_mo_ms` | 100 | Delay between actions (ms) |
| `site.page_load_timeout_ms` | 120000 | Page load timeout (2 min) |

## Adding Post-Login Steps

New steps are added as Python files in `src/sas_creator/steps/`. Each step follows the same pattern:

```python
from sas_creator.steps.base import Step, StepResult, StepStatus

class MyNewStep(Step):
    @property
    def name(self) -> str:
        return "my_step"

    @property
    def display_name(self) -> str:
        return "My New Step"

    def check_already_done(self, page) -> bool:
        # Return True if this step's outcome is already on the page
        ...

    def execute(self, page, context) -> StepResult:
        # Do your automation here
        ...
        return StepResult(status=StepStatus.SUCCESS, message="Done!")
```

Then register it in `src/sas_creator/steps/registry.py`.

## Project Structure

```
sas-creator/
├── config.yaml          # All configuration
├── .env                 # Secrets (gitignored)
├── credentials/         # e.firma files (gitignored)
├── src/sas_creator/
│   ├── __main__.py      # Entry point
│   ├── runner.py        # Main orchestration loop
│   ├── config.py        # Config loading
│   ├── state.py         # State persistence
│   ├── notifier.py      # Telegram notifications
│   ├── browser.py       # Playwright browser management
│   ├── waiter.py        # AJAX wait utilities
│   ├── takeover.py      # Human take-over detection
│   └── steps/
│       ├── base.py      # Step abstract class
│       ├── login.py     # Login step
│       └── registry.py  # Step pipeline
├── logs/                # Log files (gitignored)
├── state/               # Run state (gitignored)
└── screenshots/         # Failure screenshots (gitignored)
```
