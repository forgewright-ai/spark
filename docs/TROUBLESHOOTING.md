# Troubleshooting

This document is not tied to a spark release. It is kept up to date
as spark changes.

## The Wi-Fi does not connect

These steps are for the Arch live ISO, which uses `iwd` and `iwctl`.
Do them in order.

### 1. Run one Wi-Fi daemon

A Wi-Fi card works with one daemon. If `wpa_supplicant` runs beside
`iwd`, every `iwctl` command fails. Check:

```
ps aux | grep -iE 'wpa_supplicant|iwd' | grep -v grep
```

You should see one line, `/usr/lib/iwd/iwd`. If `wpa_supplicant` is
there too, stop it:

```
kill <pid-of-wpa_supplicant>
rm -f /etc/wpa_supplicant/wpa_supplicant.conf
systemctl restart iwd
```

### 2. Read the logs

```
journalctl -u iwd -b --no-pager | tail -25
dmesg | tail -20
```

| Log line | Meaning |
|---|---|
| `Could not register frame watch ... -114` | Another daemon has the card. Go to step 1. |
| `is another supplicant running?` | The same. |
| `authentication with <bssid> timed out` | A weak signal, or two daemons. |
| `authenticated`, `associated`, but iwctl says failed | The other daemon connected. Go to step 1. |
| `signal: -48` | The signal: -40 to -60 is good, -75 or lower is weak. |

### 3. Connect

```
iwctl station wlan0 get-networks
iwctl station wlan0 connect "<ssid>"
iwctl station wlan0 show
```

- No 5 GHz networks? Run `iw reg set US`, with your own country
  code. Wait 30 seconds and list again.
- Saved passwords are files in `/var/lib/iwd/`. Delete one to forget
  that network.
- A stale address can stay on the card. `ping -c 2 -4 archlinux.org`
  tests IPv4 alone.

### 4. Reset the card

Go one step at a time, and try to connect after each:

```
iwctl station wlan0 disconnect
systemctl restart iwd
```

Then reload the driver. `dmesg | grep -iE 'iwlwifi|mt7|rtw|ath1'`
names it.

```
ip link set wlan0 down
modprobe -r <driver> && modprobe <driver>
ip link set wlan0 up
systemctl restart iwd
```

Last, turn the machine off and unplug it for 10 seconds. A reboot does
not reset the card.

### On an installed system

With NetworkManager:

```
nmcli dev wifi
nmcli dev wifi connect "<ssid>" password '<passphrase>'
```
