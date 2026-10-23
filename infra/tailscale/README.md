# Tailscale

The app from the phone, away from home, with nothing exposed on the internet or on the home network.

```
phone, Tailscale app ──tailnet (WireGuard)──► node magazzino: a container on the network of the Docker host
                                                └─► Serve, HTTPS on 443 ──► 127.0.0.1:8000 ──► kind ──► app
```

- **One address, for good:** `https://magazzino.<tailnet>.ts.net`. It depends on the node's name and on its identity, kept in a Docker volume, not on the cluster: `make platform-down` and `make platform-up` leave it untouched, and the phone needs nothing new.
- **Only the tailnet reaches it.** The cluster publishes the app only on the PC's loopback ([cluster.tf](../platform/cluster.tf)), and the node serves it with Serve, never with Funnel: only devices logged in to the tailnet get through. A resolver on the internet knows no address for the name.
- **HTTPS with a real certificate**, from Let's Encrypt through Tailscale, which the node renews. The first request after a start takes a few seconds: the node fetches the certificate. Every certificate is listed in the public Certificate Transparency logs, name included; the tailnet's part of the name is random.
- **No secret to keep.** The node logs in once, in the browser; its identity then lives in the volume `cards-warehouse-tailscale_state`.
- **The PC off means the app out of reach.** That is expected: sales are recorded back home.
- The node is a container, like every tool here: Windows gets no network driver, and [compose.yaml](compose.yaml) pins its image by digest. What it serves is [serve/serve.json](serve/serve.json).

## The free plan, checked on 2026-10-23

The [Personal plan](https://tailscale.com/pricing): up to 6 users, unlimited personal devices, 50 tagged resources. MagicDNS, HTTPS certificates and Serve, the three features used here, are part of it. The project uses one user and two devices: the node and the phone.

## Once: set up

1. Sign up at <https://login.tailscale.com> with your Google account.
2. Run `make tailscale-up`. It starts the node and prints a login link: open it and connect the device `magazzino` to your tailnet.
3. In the [admin console](https://login.tailscale.com/admin/dns), page DNS: MagicDNS on (the default for a new tailnet), then *HTTPS Certificates*, *Enable*.
4. In the [machines](https://login.tailscale.com/admin/machines), on `magazzino`: menu, *Disable key expiry*. Otherwise after 180 days the node logs out, and the app is out of reach until a new login.
5. On the phone, install Tailscale from the app store and log in with the same account.
6. Run `make tailscale-up` again: it prints the address. Open it on the phone and add it to the home screen.

## Every day

Nothing: the node starts with Docker Desktop. `make tailscale-up` prints the address, or a login link if the node lost its identity.

- **Stop it:** `docker compose -f infra/tailscale/compose.yaml down`. The volume stays, and so does the identity.
- **Change what it serves:** edit [serve/serve.json](serve/serve.json). The node reads it again on its own.
- **Lost identity** (the volume deleted, Docker Desktop reset): first delete the old `magazzino` in the machines of the admin console, then `make tailscale-up` and log in again. Same name, same address. Otherwise the new node is `magazzino-1`.

## Checks

```sh
make tf-check                            # unit tests, in the pipeline too
bash infra/tailscale/tests/acceptance.sh # inside make shell, with the platform up and the node logged in
```

Two unit tests in [platform.tftest.hcl](../platform/tests/platform.tftest.hcl) read `serve.json` against the platform's plan: the phone's HTTPS address on 443 leads to the PC port where the cluster publishes the app's node port, and that port listens only on the loopback, with Funnel never on.

The acceptance test checks that the node is online as `magazzino`, that its key never expires, that the app answers healthy over HTTPS from inside the tailnet, entering it through the node, with curl checking the certificate as a browser does, and that public DNS gives the internet no route to it. It prints the address. Run it again after `make platform-down` and `make platform-up`: the same address, still green.

The phone's own checks are by hand: on mobile data with Tailscale on, the app opens with a valid certificate and the login works; with Tailscale off, the address does not answer; on the home Wi-Fi without Tailscale, neither the address nor the PC's IP on port 8000 answers.
