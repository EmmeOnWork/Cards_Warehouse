# eBay

How the app reaches Manuel's eBay account, how to connect it, set it up, renew it and cut it off, and how the app publishes a listing there by itself.

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
| `EBAY_FULFILLMENT_POLICY_ID` | The seller's shipping policy on eBay Italy | Made by Manuel on eBay's page, read by `make ebay-setup` |
| `EBAY_PAYMENT_POLICY_ID` | The payment policy | `make ebay-setup` |
| `EBAY_RETURN_POLICY_ID` | The return policy | `make ebay-setup` |
| `EBAY_LOCATION_KEY` | The place the goods leave from, `magazzino` | `make ebay-setup` |

Sandbox and production have separate keysets, credentials, policies and locations. Switching to the real account (task 37) means replacing all nine values together: `make ebay-connect`, then `make ebay-setup`, both on `production`.

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

## Setting up the seller

A listing needs three business policies of the seller on eBay Italy (shipping, payment, returns) and a place the goods leave from. Once per account, after `make ebay-connect`:

1. **Make the shipping policy on eBay's page.** In production: *Seller Hub*, *Account*, *Business policies*, *Create policy*, *Shipping*. On the sandbox, the same page of the sandbox's My eBay, signed in as the test user. Pick the shipping service and its price there: the code of a service comes only from an older API of eBay (the Trading API), which on the sandbox does not always answer.
2. Run `make ebay-setup`. It asks for the environment, the client ID, the client secret and `EBAY_REFRESH_TOKEN` (the last two not shown as you type them), then the postal code and city the goods leave from. eBay shows buyers the city, never a street. It then:
   - joins the business policies (`SELLING_POLICY_MANAGEMENT`), if the account has not yet;
   - takes the shipping policy, and asks which one when there are several;
   - takes the first payment and return policy on eBay Italy, or makes *Pagamento (app)* and *Nessun reso (app)* when there are none. A private seller does not have to accept returns. Change the one it made on eBay's page if you want them;
   - makes the location `magazzino`, if eBay does not have it.
3. Put the four values it prints in Infisical, next to the others.

Run again, it makes nothing twice: what eBay has already is taken.

## Publishing on eBay by itself

eBay stays a manual channel, with its actions in *Da fare*, until it is switched on its page: *Canali*, *eBay*, *Pubblica da sola con l'API*. *Torna manuale* switches it back. Nothing else in the app changes: the pages hand every channel's work to one object, which asks eBay's adapter (`ebay_channel.py`) for the channels switched, and leaves the rest to Manuel. Updates and closings stay actions for Manuel until tasks 34 and 35.

Put on sale on eBay, a listing is published in four steps, before the item's page comes back:

1. **The photos.** For each photo, in its order, the app gives eBay its link to the bucket, signed for 5 minutes (Media API, `createImageFromUrl`). eBay downloads it at once into its own servers and answers with its copy's address. The bucket stays private and the photo does not go through the pod. eBay keeps its copy while a listing shows it.
2. **The item** (Inventory API, `createOrReplaceInventoryItem`): the texts of the listing, the condition, the photos and the copies. One item on eBay for each listing of the app, `listing-<number>`.
3. **The offer**: the price, in euros on eBay Italy, the copies, the category and the four values of the setup.
4. **The publication** makes the offer a listing. The listing is active, with its link: `https://www.ebay.it/itm/<number>`, or on the sandbox `https://sandbox.ebay.com/itm/<number>`.

Only single cards and sealed products are published:

| Item | Category | Condition |
|---|---|---|
| Sealed | 261044, CCG Sealed Boxes, for every sealed: its type is free text | `NEW` |
| Card not graded | 183454, CCG Individual Cards | `USED_VERY_GOOD` (eBay's 4000, *Ungraded*), with the descriptor 40001: Mint and Near Mint 400010, Excellent and Good 400015, Light Played and Played 400016, Poor 400017 |
| Graded card | 183454 | `LIKE_NEW` (eBay's 2750, *Graded*), with the grader (27501: PSA 275010, BGS 275013, CGC 275015…, *Other* 2750123 for a grader eBay does not list) and the grade (27502: 10 is 275020, down in half points to 1, 2750218) |

**When eBay cannot take it**, the listing stays *da pubblicare*, and the item's page says why under the listings, with *Riprova su eBay*. What the app can tell before asking eBay, it tells before: eBay not connected, the setup missing, no photo, a magazine or the bulk, a card without its condition. eBay's own refusals come in its words, in English, after *eBay rifiuta l'annuncio:*. When eBay refuses at the last step, the offer stays on eBay. *Riprova* takes it up with the values of now, for example a policy corrected in Infisical, instead of making a second one.

## The answers recorded

The tests run against a fake eBay (`tests/fake_ebay.py`), and also against the answers the sandbox gave, kept in `app/tests/ebay_responses/sandbox.json` (`tests/test_ebay_recorded.py`). To record them, or record them again after a change in the adapter:

1. Run `make ebay-record`, with the sandbox's values: client ID, client secret and durable credential, then postal code and city. It runs on a PostgreSQL of its own, not the cluster's.
2. It sets up the seller as `make ebay-setup` does, then publishes three listings on the sandbox: a sealed box, a card not graded and a card graded PSA 10, each with eBay's logo as its photo. The bucket is private, and eBay needs a public address. It asks for the box again, as *Riprova* does, and reads the conditions eBay lists for single cards.
3. It prints each listing's link, or why eBay refused it, and writes the file. Neither the answers of the token nor the requests are kept: no credential and no link of the bucket are in it.

The three listings stay on the sandbox, where nobody buys them.

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

### Checked during task 33 (2026-10-29)

| Question | Answer | Source |
|---|---|---|
| How do the photos, in a private bucket, reach eBay? | With the Media API: `createImageFromUrl` takes an HTTPS address, downloads the picture into eBay's servers and answers with its address there, which goes in `product.imageUrls`. Supported on the sandbox (`apim.sandbox.ebay.com`). An image no active listing uses is removed after its expiration date. The bucket's link signed for 5 minutes is enough. | [Media API overview](https://www.developer.ebay.com/api-docs/commerce/media/overview.html), [createImageFromUrl](https://developer.ebay.com/api-docs/commerce/media/resources/image/methods/createImageFromUrl) |
| What must an offer have to be published? | The seller joined to the business policies, the three policies and a location (`merchantLocationKey`). | [Publishing offers](https://developer.ebay.com/api-docs/sell/static/inventory/publishing-offers.html), [inventory locations](https://developer.ebay.com/api-docs/sell/static/inventory/managing-inventory-locations.html) |
| What condition does a single card take? | Graded (2750, `LIKE_NEW`) with grader and grade, or not graded (4000, `USED_VERY_GOOD`) with the state of the card (40001). eBay refuses any other. | [Condition descriptors for trading cards](https://developer.ebay.com/api-docs/user-guides/static/mip-user-guide/mip-enum-condition-descriptor-ids-for-trading-cards.html), [eBay community](https://community.ebay.com/t5/Seller-Tools/error-message-Error-The-Condition-descriptor-Near-Mint-or-Better/m-p/33956400) |
| Can the shipping policy be made by the API? | Yes, but it needs the code of a shipping service, which comes from the Trading API (`GeteBayDetails`). On the sandbox it does not always answer: Manuel makes it on eBay's page. | [Shipping carrier and service values](https://developer.ebay.com/api-docs/sell/static/seller-accounts/ht_shipping-setting-shipping-carrier-and-service-values.html), [eBay community](https://community.ebay.com/t5/Token-Messaging-Sandbox-related/can-not-get-Shipping-service-details-in-sandbox-required-for/td-p/34959807) |

**Still to confirm on the sandbox, with `make ebay-record`:** category 261044 for the sealed products (seen only in a URL of ebay.com), category 183454 on eBay Italy, and the values of the descriptors. Sellers' posts give 400011 to 400013 for the state of a card, and others give 400015 to 400017 for card games. The values of the graders and the grades come from no page found. `tests/test_ebay_recorded.py` checks them all against what eBay lists. Also to confirm: the address of a sandbox listing, and eBay's answer to a second offer for the same item (`offerId` among the parameters of the error).

The other questions of task 31 (selling API with a private account, production keys and the account deletion notifications, call limits) concern tasks 35 to 37 and are still open.
