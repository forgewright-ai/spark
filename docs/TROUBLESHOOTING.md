# Troubleshooting

This document is not tied to a spark release. It is kept true as
things change, and no release waits on it.

## The Wi-Fi adapter and connection

A machine on Wi-Fi that will not connect looks broken in 5 ways at
once. It is almost always one cause. Work this section top to bottom,
in order.

This applies to the Arch live ISO, which runs `iwd` and `iwctl`, and,
where noted, to an installed system running NetworkManager.

### One Wi-Fi daemon per card

A Wi-Fi card obeys one manager. On the Arch live ISO that manager is
`iwd`. When a `wpa_supplicant` also runs, started by hand or left over
from an earlier attempt, every `iwctl` command fails with misleading
errors. Meanwhile the second daemon connects on its own.

Check for a second daemon before anything else:

```
ps aux | grep -iE 'wpa_supplicant|iwd' | grep -v grep
```

Healthy output is one line: `/usr/lib/iwd/iwd`. If a `wpa_supplicant`
appears, that is your whole problem:

```
kill <pid-of-wpa_supplicant>
rm -f /etc/wpa_supplicant/wpa_supplicant.conf
systemctl restart iwd
```

Then connect as usual. This comes before anything else.

### The logs first

Two commands name the real problem. Run them after any failure:

```
journalctl -u iwd -b --no-pager | tail -25
dmesg | tail -20
```

How to read what they say:

| Log line | Meaning |
|---|---|
| `Could not register frame watch ... -114` | Another daemon owns the card. One daemon per card, above. |
| `Unexpected connection related event -- is another supplicant running?` | The same. iwd says it outright. |
| `event: connect-failed, status: 1` | iwd's attempt was refused. Check the dmesg side. |
| `wlan0: authentication with <bssid> timed out`, repeating | Auth frames not answered: a weak signal, or two daemons taking turns. |
| `wlan0: authenticated` then `associated`, but iwctl says failed | The other daemon connected, not iwd. One daemon per card. |
| `event: connect-info ... signal: -48` | The signal report. -40s is excellent, -60s fine, -75 and worse is trouble. |

### The reset ladder

When the card seems stuck, go up one rung at a time and test again
after each:

```
iwctl station wlan0 disconnect        # 1. stand down a wedged attempt
systemctl restart iwd                 # 2. a fresh daemon
ip link set wlan0 down
modprobe -r <driver> && modprobe <driver>
ip link set wlan0 up
systemctl restart iwd                 # 3. a fresh driver (find <driver> below)
# 4. a cold boot: full power off, cord out for 10 seconds. A warm
#    reboot does not reset the card.
```

Find `<driver>` first. dmesg names it:

```
dmesg | grep -iE 'iwlwifi|mt7|rtw|ath1'
```

`iwlwifi` is Intel, `mt79xx` is MediaTek, `rtw` is Realtek, `ath` is
Qualcomm. In the real session below, the card announced itself as
`iwlwifi` after an hour of MediaTek guesses. dmesg knows.

### Scanning and connecting with iwctl

```
iwctl station wlan0 show              # state: connected / disconnected / connecting
iwctl station wlan0 get-networks      # the networks, security, signal bars
iwctl station wlan0 connect "<ssid>"  # asks for the passphrase
iwctl station wlan0 connect-hidden "<ssid>"   # a network that does not broadcast
```

Things worth knowing:

- `station wlan0 scan` refusing with `Operation not supported` does not
  block you. iwd scans on its own, and `show` says `Scanning: yes`
  after a daemon restart. `get-networks` reads those results.
- Missing 5 GHz networks? The live ISO boots in the world regulatory
  domain, which mutes many 5 GHz channels. The fix is `iw reg set US`,
  with your own country code. Wait 30 seconds and list again.
- Saved credentials live as files in `/var/lib/iwd/`, one `.psk` file
  per network. `ls` that directory to see what is cached, and `rm` a
  file to forget a network. An empty directory means nothing was ever
  saved, so a "cached bad password" theory is dead on arrival.
- The command is `iwctl`. Under stress it becomes iwclt, iwcl and
  mobprobe. zsh's autocorrect is on your side: read its prompt.

### IP-level checks

```
ip a                                  # the addresses on wlan0
ping -c 2 -4 archlinux.org            # force IPv4
```

- A stale address can linger on the interface after a dropped
  connection. A stale IPv6 address makes a bare `ping` try IPv6 and
  fail in a confusing way. `-4` cuts through.
- Your router's client list is a cache, not the truth. It showing the
  machine "connected" proves only that something held a lease
  recently. `iwctl station wlan0 show` is the live answer. Trust it.

### Pick the right access point

The signal bars from `get-networks` decide which network to join, not
habit. A mesh or bridge node one room away beats the main gateway two
floors up. After connecting, `iwctl station wlan0 show` reports the
BSSID, the band and the signal you landed on.

On the installed system, with NetworkManager, the same check is:

```
nmcli dev wifi                        # the list, with signal
nmcli dev wifi connect "<ssid>" password '<passphrase>'
```

### A real session

Symptoms, in the order they appeared:

1. `iwctl station wlan0 connect "<gateway-ssid>"` answered `Operation
   failed` at once, with the passphrase correct.
2. `iwctl station wlan0 scan` answered `Operation not supported`, again
   and again, and survived `systemctl restart iwd`.
3. The router's client page showed the machine connected with an IP.
   `iwctl` said `disconnected`. The stale IP was visible in `ip a`.
4. `dmesg` showed `authentication ... timed out` against both gateway
   radios, `..:04` and `..:08`. Minutes later it showed a successful
   `authenticated` and `associated` that nobody seemed to own.
5. Theories burned along the way: a weak signal, a wedged card, a
   cached bad password, a WPA3 handshake quirk, the wrong driver.

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

The root cause: a `wpa_supplicant` started by hand early in the
session, the classic first-guide attempt, held `wlan0` the whole time.
It caused symptoms 1 to 4 by itself. It blocked iwd's connects and
scans, it was the "connected" client the router saw, and it owned the
mystery association in dmesg. The signal was never weak. The machine
was fighting over the card and measuring the far access point.

The fix, 3 commands and 10 seconds:

```
kill 1058
rm /etc/wpa_supplicant/wpa_supplicant.conf
systemctl restart iwd
iwctl station wlan0 connect "<home-ssid>"     # connected, -48 dBm
```

The lesson: the first two sections exist because every minute spent
on theories was answered, in plain English, by a log nobody had read
yet.
