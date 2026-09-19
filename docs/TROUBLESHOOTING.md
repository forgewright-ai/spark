# Troubleshooting

This document is not tied to a spark release. It is kept true as
things change, but it is outside the landing rule: nothing here has to
appear in `spark help`, `CHEATSHEET.txt` or a `CHANGELOG.md` entry,
and no release waits on it.

## WiFi adapter and connection

A spark box on WiFi that will not connect looks broken in five different
ways at once. It is almost always one cause. Work this section top to
bottom; do not skip to theories.

This applies to the Arch live ISO (`iwd` + `iwctl`) and, where noted, to
an installed system running NetworkManager.

---

### Rule 0: one WiFi daemon per card

A WiFi card obeys exactly one manager. On the Arch live ISO that manager
is `iwd`. If a `wpa_supplicant` is also running -- started by hand, or
left over from an earlier attempt -- every `iwctl` command fails with
misleading errors while the rogue daemon quietly connects on its own.

Check for squatters before anything else:

```
ps aux | grep -iE 'wpa_supplicant|iwd' | grep -v grep
```

Healthy output is ONE line: `/usr/lib/iwd/iwd`. If a `wpa_supplicant`
appears, that is your whole problem:

```
kill <pid-of-wpa_supplicant>
rm -f /etc/wpa_supplicant/wpa_supplicant.conf
systemctl restart iwd
```

Then connect normally. Do not debug anything else first.

---

### Rule 1: pull the logs before forming a theory

Two commands name the real problem. Run them after any failure:

```
journalctl -u iwd -b --no-pager | tail -25
dmesg | tail -20
```

How to read what they say:

| Log line | Meaning |
|---|---|
| `Could not register frame watch ... -114` | Another daemon owns the card. Go to Rule 0. |
| `Unexpected connection related event -- is another supplicant running?` | Same. iwd is telling you outright. |
| `event: connect-failed, status: 1` | iwd's attempt was refused -- check the dmesg side. |
| `wlan0: authentication with <bssid> timed out` (repeating) | Auth frames not answered: weak signal, or two daemons interleaving. |
| `wlan0: authenticated` then `associated` ... but iwctl says failed | The OTHER daemon connected, not iwd. Rule 0. |
| `event: connect-info ... signal: -48` | Signal report. -40s excellent, -60s fine, -75 and worse is trouble. |

---

### The reset ladder

When the card seems stuck, escalate one rung at a time, retesting
after each:

```
iwctl station wlan0 disconnect        # 1. stand down a wedged attempt
systemctl restart iwd                 # 2. fresh daemon
ip link set wlan0 down
modprobe -r <driver> && modprobe <driver>
ip link set wlan0 up
systemctl restart iwd                 # 3. fresh driver (see below for <driver>)
# 4. cold boot: full power off, cord out 10 seconds. A warm reboot
#    does not reset the card.
```

Find `<driver>` first -- do not guess it:

```
dmesg | grep -iE 'iwlwifi|mt7|rtw|ath1'
```

`iwlwifi` = Intel, `mt79xx` = MediaTek, `rtw` = Realtek, `ath` =
Qualcomm. (Field note: this box's card announced itself as `iwlwifi`
after an hour of MediaTek assumptions. dmesg knows; assumptions don't.)

---

### Scanning and connecting with iwctl

```
iwctl station wlan0 show              # state: connected / disconnected / connecting
iwctl station wlan0 get-networks      # list SSIDs, security, signal bars
iwctl station wlan0 connect "<ssid>"  # prompts for the passphrase
iwctl station wlan0 connect-hidden "<ssid>"   # for non-broadcast SSIDs
```

Things worth knowing:

- `station wlan0 scan` refusing with `Operation not supported` does NOT
  block you. iwd scans on its own (`show` says `Scanning: yes` after a
  daemon restart); `get-networks` reads those results.
- Missing 5 GHz networks? The live ISO boots in the world regulatory
  domain, which mutes many 5 GHz channels. Fix: `iw reg set US` (your
  country code), wait ~30 s, list again.
- Saved credentials live as files in `/var/lib/iwd/` (one `.psk` per
  network). `ls` that directory to see what is cached; `rm` a file to
  forget a network. An empty directory means nothing was ever saved --
  a "cached bad password" theory is dead on arrival.
- The command is `iwctl`. Under stress it becomes iwclt, iwcl, and
  mobprobe. zsh's autocorrect is on your side; read its prompt.

---

### IP-level checks

```
ip a                                  # addresses on wlan0
ping -c 2 -4 archlinux.org            # force IPv4
```

- A stale address can linger on the interface after a dropped
  connection, and a stale IPv6 SLAAC address will make a bare `ping`
  try IPv6 and fail confusingly. `-4` cuts through.
- Your router's client list is a CACHE, not the truth. It showing the
  box "connected" proves only that something held a lease recently.
  `iwctl station wlan0 show` is the live answer -- trust it.

---

### Pick the right access point

`get-networks` signal bars decide which SSID to join, not habit. A
mesh or bridge node one room away beats the main gateway two floors
up. After connecting, `iwctl station wlan0 show` reports the BSSID,
band, and RSSI you actually landed on.

On the installed system (NetworkManager) the same check is:

```
nmcli dev wifi                        # list with signal
nmcli dev wifi connect "<ssid>" password '<passphrase>'
```

---

### Worked example (a real session, names changed)

Symptoms, in the order they appeared:

1. `iwctl station wlan0 connect "<gateway-ssid>"` -> `Operation failed`,
   instantly, passphrase correct.
2. `iwctl station wlan0 scan` -> `Operation not supported`, repeatedly,
   surviving `systemctl restart iwd`.
3. Router's client page showed the box connected with an IP; `iwctl`
   said `disconnected`. The stale IP was visible in `ip a`.
4. `dmesg` showed `authentication ... timed out` against both gateway
   radios (`..:04`, `..:08`) -- then, minutes later, a successful
   `authenticated` / `associated` nobody seemed to own.
5. Theories burned along the way: weak signal, wedged card, cached bad
   password, WPA3 handshake quirk, wrong driver.

The log pull that ended it:

```
journalctl -u iwd -b --no-pager | tail -25
  ...
  iwd[1708]: Could not register frame watch type 00d0: -114
  iwd[1708]: Unexpected connection related event -- is another supplicant running?
  iwd[1708]: event: connect-info, ssid: <home-ssid>, bss: ..:05, signal: -57
  iwd[1708]: event: connect-failed, status: 1

ps aux | grep -iE 'wpa_supplicant|iwd' | grep -v grep
  root  1058  ... /usr/bin/wpa_supplicant -B -i wlan0 -c /etc/wpa_supplicant/wpa_supplicant.conf
  root  1708  ... /usr/lib/iwd/iwd
```

Root cause: a `wpa_supplicant` started by hand early in the session
(the classic first-guide attempt) held `wlan0` the entire time. It
caused symptoms 1-4 single-handedly: it blocked iwd's connects and
scans, it was the "connected" client the router saw, and it owned the
mystery association in dmesg. The signal was never weak -- the box was
simply fighting over the card and measuring the far AP.

The fix, three commands and ten seconds:

```
kill 1058
rm /etc/wpa_supplicant/wpa_supplicant.conf
systemctl restart iwd
iwctl station wlan0 connect "<home-ssid>"     # connected, -48 dBm
```

Lesson: Rule 0 and Rule 1 exist because every minute spent on theories
was answered, in plain English, by a log we had not read yet.
