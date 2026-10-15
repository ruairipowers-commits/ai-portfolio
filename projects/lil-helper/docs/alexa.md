# Lil'Helper on Alexa

"Alexa, ask Lil'Helper what's for dinner." The skill answers from your household's plan, using the same rules as the
microphone button in the app. It can't spend money, and planning a week still needs an adult.

What you can say (after "Alexa, ask Lil'Helper…"):

| Say | What happens |
|---|---|
| what's for dinner / what's for lunch tomorrow | the meal, and who's cooking |
| what's on the shopping list | the first store's list, read out |
| what are my jobs | your jobs today |
| I have half a chicken, rice and broccoli | the best match from your recipe book (the full list is in the app) |
| I have 30 minutes and want something cozy | Vibe cooking ideas |
| surprise me | anything safe from the book |
| we have 3 portions of overnight oats left | updates the weekly buffet count |
| dinner was all gone / some left / lots left | how much was left |
| rate dinner 5 stars | a rating |
| plan next week | drafts it (adults only); approve it in the app |

## How it works

Amazon sends each request to `https://<your server>/alexa`. The server checks it before reading it: Amazon's
certificate URL, the certificate chain (valid, trusted, issued to `echo-api.amazon.com`), the RSA-SHA256 signature
of the body, a timestamp within 150 seconds, and your skill id. Anything else is refused with a 400.

Each person links their own Alexa, so "what are my jobs" knows who's asking. Linking uses a one-time code from the
app (ten minutes); Amazon is given a long random token and the server stores only its hash. **Settings → Alexa →
Unlink** removes it.

## Set it up (about 20 minutes, once per server)

You need an Amazon developer account (free) and the server reachable over HTTPS with a real certificate.

1. Go to <https://developer.amazon.com/alexa/console/ask> → **Create Skill**. Name: *Lil'Helper*. Type: **Other →
   Custom**. Hosting: **Provision your own**. Template: **Start from scratch**.
2. **Build → Interaction Model → JSON Editor**: paste `alexa/interaction-model.json` from this repo. **Save**, then
   **Build skill**.
3. **Build → Endpoint**: choose **HTTPS**. Default region: `https://<your server>/alexa`. SSL certificate type: *My
   development endpoint has a certificate from a trusted certificate authority*. **Save**.
4. Copy the **Skill ID** (top of the page, `amzn1.ask.skill.…`) into the server's environment:
   `HELPER_ALEXA_SKILL_ID=amzn1.ask.skill.…`, then restart the server.
5. **Build → Tools → Account Linking**: turn on *Do you allow users to link accounts*. Choose **Implicit Grant**.
   - Your Web Authorization URI: `https://<your server>/alexa/link`
   - Your Client ID: `lilhelper` (any value; the server doesn't use it)
   - Scope: `household`
   - **Save**.
6. **Test** tab → set testing to **Development**. Skills in development work on every Echo signed in to your Amazon
   account; you don't have to publish it.
7. In the Lil'Helper app: **Settings → Alexa → Get a code**. In the Alexa app: **More → Skills & Games → Your Skills
   → Dev → Lil'Helper → Enable**, type the code. Repeat step 7 for each person with their own Amazon account.

Try: "Alexa, open Lil'Helper", then "what's for dinner".

## Local testing

`HELPER_ALEXA_VERIFY=0` skips the certificate and signature checks (the skill id and timestamp are still checked) so
you can post sample requests with curl. It's ignored when `HELPER_ENV=production`. The tests in
`tests/test_alexa.py` cover the signature check with a test key, the URL rules from Amazon's documentation, linking,
and the intents. The certificate-chain check is exercised against a self-signed certificate (refused); a real
Amazon certificate couldn't be fetched from the build sandbox, so the first live request from the **Test** tab is the
check that it accepts Amazon's.

## Limits

- Alexa hears free speech only in "I have …" (the `CookWithIntent` uses a free-text slot); other requests follow
  the sample phrases in the interaction model.
- Answers are short on purpose; the card in the Alexa app repeats them, and the app has the detail.
- Nothing is bought by voice. A week planned by voice is a draft until an adult approves it in the app.
