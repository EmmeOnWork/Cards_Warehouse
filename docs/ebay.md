# eBay

How the app reaches Manuel's eBay account, and how to connect it, renew it and cut it off.

## How it works

The app acts on the account through eBay's OAuth, with an authorization Manuel grants and can revoke. It never knows the password of the account.

```
make ebay-connect (PC) ─► link ─► browser: sign in on eBay, agree ─► eBay's own page, a code in its address
        ◄──────────── address pasted back ◄─────────────────────────────────┘
        └─► code traded for the durable credential ─► printed once ─► pasted into Infisical, /app
                                                                          │
app (cluster) ◄── operator ◄──────────────────────────────────────────────┘
   └─► asks eBay for a token of 2 hours when a call needs one, reuses it until 5 minutes before its end
```

- **Nothing on the PC answers eBay**, and the app is not on the internet. After the consent eBay sends the browser to a page of its own, and the code travels by copy and paste.
- **The durable credential** is eBay's refresh token. It lasts about 18 months. It lives in Infisical: not in the database, not in a file, not in Git. The app logs neither it nor the short-lived tokens. The code never runs a log line with one, and a test checks the log of the HTTP client too.
- **The short-lived tokens** last 2 hours. The app gets one from eBay with the durable credential when a call needs it, and keeps it in memory.
- **The eBay page** (`/ebay`) shows whether the account is connected, the environment (*Prova (sandbox)* or *Reale*) and the day the authorization ends. *Collegato* means that eBay has just given a token for the account. A stored credential alone proves nothing. When eBay refuses the authorization, refuses the app's keys or does not answer, the page says so in red.

## The values in Infisical

All in the project `cards-warehouse`, environment `prod`, folder `/app`. The chart lists them as optional: until they exist, the app starts and the page says *Non collegato*.

| Name | What it is | Where it comes from |
|---|---|---|
| `EBAY_ENVIRONMENT` | `sandbox` or `production` | `make ebay-connect` |
| `EBAY_CLIENT_ID` | The App ID of the keyset | Developer portal, *Application Keys* |
| `EBAY_CLIENT_SECRET` | The Cert ID of the same keyset | Developer portal, *Application Keys* |
| `EBAY_REFRESH_TOKEN` | The durable credential | `make ebay-connect` |
| `EBAY_AUTHORIZATION_EXPIRES` | When it ends, in UTC | `make ebay-connect`, from the lifetime eBay gives with the credential |

Sandbox and production have separate keysets and separate credentials. Switching to the real account (task 37) means replacing all five values together.

## Before the first connection

Once, on [developer.ebay.com](https://developer.ebay.com/develop/get-started):

1. Create the developer account.
2. In *Application Keys*, create the **Sandbox** keyset. Put its App ID in Infisical as `EBAY_CLIENT_ID` and its Cert ID as `EBAY_CLIENT_SECRET`.
3. Create a **sandbox test user**: *User Access Tokens*, then *Register a new Sandbox user* on the *User Tokens (eBay Sign-In)* page ([eBay's guide](https://developer.ebay.com/api-docs/static/gs_create-a-test-sandbox-user.html)). The sandbox has accounts of its own, separate from ebay.com, and the real account does not exist there: the app is tried on the sandbox before it touches the real listings. eBay puts `TESTUSER_` before the name you choose. The email must not belong to another test user. The password needs 8 to 64 characters, with at least a letter, a number and a symbol.
4. In *User Tokens*, under *Get a Token from eBay via Your Application*, add an eBay redirect URL: eBay creates the **RuName**, the name it uses in place of a return address. Enable OAuth for it and leave the accept and decline URLs empty. eBay then uses pages of its own, so nothing on the PC or in the cluster needs an address on the internet.

These steps were written on 2026-10-23 from the sources below, before the first connection: correct them if the portal differs.

## Connect, and connect again

1. Run `make ebay-connect`. It asks for the environment (`sandbox` unless you type `production`), the client ID, the client secret (not shown as you type it) and the RuName.
2. Open the link it prints in a **private window** of the browser, so that no eBay session already open stands in for the account. Sign in with the sandbox test user, by its whole name, `TESTUSER_` included, and agree. The email and password of ebay.com are refused there. In production, sign in with the real account.
3. eBay leaves you on a page of its own. Copy the **whole address** from the address bar and paste it back within 5 minutes: the code in it lasts 299 seconds and works once.
4. Put the three values it prints in Infisical, replacing the old ones. Within a minute the operator copies them into the cluster and restarts the app. The eBay page then says *Collegato*, with the new end date.

A code pasted late, or twice, makes eBay refuse it (`invalid_grant`): start again from step 1. A typing error in the client ID or secret ends the same way, with `invalid_client`.

If the link itself answers `{"error_id":"unauthorized_client","error_description":"The OAuth client was not found."}`, the client ID is not a sandbox App ID. The production one has `-PRD-` in it, the sandbox one `-SBX-`. The Dev ID or a half-copied App ID give the same answer.

## Renewal

The durable credential is not renewed by use: it ends on the day the eBay page shows. Before that day, connect again as above. A new consent gives a new credential and a new date.

Connect again also when the page says *eBay non accetta più l'autorizzazione*. eBay refuses the credential when it has expired, when the app was removed from the account, and when the password or the user name of the account changed.

If the page says *eBay rifiuta la richiesta (invalid_client)*, the keys in Infisical are wrong: copy `EBAY_CLIENT_ID` and `EBAY_CLIENT_SECRET` again from the developer portal.

## Cutting it off

- **On eBay**, remove the app from the applications with access to the account. A token the app already holds keeps working until its 2 hours end. After that the app asks for a new one, eBay refuses, and the page shows the warning.
- **On the app's side**, delete `EBAY_REFRESH_TOKEN` from Infisical: the app restarts and the page says *Non collegato*.

## What was checked (task 31, 2026-10-23)

The pages of developer.ebay.com refuse automated reading, so these answers come from eBay's knowledge base and community and from two guides written by others. `make ebay-connect` does not trust any of the numbers below: it uses the lifetime eBay returns with the credential.

| Question | Answer | Source |
|---|---|---|
| How long does the durable credential last? | About 18 months: `refresh_token_expires_in` is 47,304,000 s in the answers quoted. | [databaaba](https://www.databaaba.com/blog/ebay-oauth-connect-seller-account/), [eBay community](https://community.ebay.com/t5/eBay-APIs-Talk-to-your-fellow/How-to-generate-a-new-refresh-token/m-p/33898456) |
| And a short-lived token? | 7,200 s, 2 hours. | [eBay, authorization code grant](https://developer.ebay.com/api-docs/static/oauth-auth-code-grant-request.html), as quoted by search |
| How is a short-lived token renewed? | `grant_type=refresh_token` with the durable credential and the scopes again. The durable credential does not change. | [databaaba](https://www.databaaba.com/blog/ebay-oauth-connect-seller-account/), [rickapps](https://gist.github.com/rickapps/1be821cd515f8cc946f292b715f893db) |
| How is the durable credential renewed? | It is not: a new consent gives a new one. | [rickapps](https://gist.github.com/rickapps/1be821cd515f8cc946f292b715f893db), [eBay knowledge base 5218](https://developer.ebay.com/support/knowledge-base/5218) |
| What does a revocation look like? | `invalid_grant` on renewal. Causes: the app removed from the account, a new password or user name, eBay's support. | [eBay knowledge base 5218](https://developer.ebay.com/support/knowledge-base/5218) |
| Can the consent work without an address on the internet? | Yes: with the accept URL left empty eBay shows its own page, and the code (299 s) is in its address. | [databaaba](https://www.databaaba.com/blog/ebay-oauth-connect-seller-account/), [rickapps](https://gist.github.com/rickapps/1be821cd515f8cc946f292b715f893db) |

The other questions of task 31 (selling API with a private account, production keys and the account deletion notifications, call limits, photos) concern tasks 33 to 37 and are still open.
