#!/usr/bin/env bash

set -uo pipefail

DOMAIN="iomreliccalc.me"
WWW="www.${DOMAIN}"
ASSET="https://${DOMAIN}/static/css/style.min.css"
NS_WANTED="hassan.ns.cloudflare.com tani.ns.cloudflare.com"

CF_PREFIXES="104.16. 104.17. 104.18. 104.19. 104.20. 104.21. 104.22. 104.23.
104.24. 104.25. 104.26. 104.27. 172.64. 172.65. 172.66. 172.67. 172.68.
172.69. 162.159. 188.114. 198.41."

pass_count=0
fail_count=0
critical_failed=0

if [ -t 1 ]; then
    GREEN=$'\033[32m'; RED=$'\033[31m'; DIM=$'\033[90m'; YELLOW=$'\033[33m'; OFF=$'\033[0m'
else
    GREEN=""; RED=""; DIM=""; YELLOW=""; OFF=""
fi

if command -v dig >/dev/null 2>&1; then HAVE_DIG=1; else HAVE_DIG=0; fi

row() {
    local kind="$1" check="$2" expected="$3" actual="${4:-}" ok="$5" tag
    [ -n "$actual" ] || actual="(no answer)"
    if [ "$ok" -eq 0 ]; then
        printf '  %s[OK  ]%s %-34s %swant: %-38s%s got: %s\n' \
            "$GREEN" "$OFF" "$check" "$DIM" "$expected" "$OFF" "$actual"
        pass_count=$((pass_count + 1))
    else
        if [ "$kind" = critical ]; then tag="FAIL"; critical_failed=1; else tag="WAIT"; fi
        printf '  %s[%s]%s %-34s %swant: %-38s%s got: %s\n' \
            "$RED" "$tag" "$OFF" "$check" "$DIM" "$expected" "$OFF" "$actual"
        fail_count=$((fail_count + 1))
    fi
    return 0
}

skip_section() {
    printf '  %s[SKIP] %s - install dig (apt install dnsutils), or run check-dns.ps1 on Windows%s\n' \
        "$DIM" "$1" "$OFF"
}

section() {
    printf '  %s%s%s\n' "$YELLOW" "$1" "$OFF"
    printf '  %s\n' "$(printf '%.0s-' $(seq 1 110))"
}

dig_short() { dig +short +time=5 +tries=2 "$@" 2>/dev/null | sed 's/\.$//' | sort | tr '\n' ' ' | sed 's/ $//'; }

is_cf_ip() {
    local ip="$1" prefix
    for prefix in $CF_PREFIXES; do
        case "$ip" in "$prefix"*) return 0 ;; esac
    done
    return 1
}

all_cf_ips() {
    local ips="$1" ip
    [ -n "$ips" ] || return 1
    for ip in $ips; do is_cf_ip "$ip" || return 1; done
    return 0
}

headers() {
    local url="$1" follow="-L"
    [ "${2:-}" = "--no-redirect" ] && follow=""
    curl -sS -I --max-time 15 $follow "$url" 2>/dev/null
}

header_value() { printf '%s' "$1" | tr -d '\r' | grep -i "^$2:" | tail -1 | cut -d: -f2- | sed 's/^ *//'; }
first_status() { printf '%s' "$1" | grep -oE '^HTTP/[^ ]+ [0-9]{3}' | head -1 | grep -oE '[0-9]{3}$'; }
last_status()  { printf '%s' "$1" | grep -oE '^HTTP/[^ ]+ [0-9]{3}' | tail -1 | grep -oE '[0-9]{3}$'; }

printf '\n  Cloudflare cutover check - %s\n' "$DOMAIN"
printf '  %s\n\n' "$(date '+%Y-%m-%d %H:%M:%S')"

section "DELEGATION"

if [ "$HAVE_DIG" -eq 0 ]; then
    skip_section "delegation checks need dig"
else
    for pair in "Google:8.8.8.8" "Cloudflare:1.1.1.1" "Quad9:9.9.9.9"; do
        label="${pair%%:*}"
        server="${pair##*:}"
        got="$(dig_short NS "$DOMAIN" "@$server")"
        ok=1
        for want in $NS_WANTED; do
            case " $got " in
                *" $want "*) ok=0 ;;
                *) ok=1; break ;;
            esac
        done
        kind=critical
        [ "$label" = "Google" ] && kind=soft
        row "$kind" "NS via $label" "hassan + tani .ns.cloudflare.com" "$got" "$ok"
    done

    soa="$(dig +short +time=5 SOA "$DOMAIN" @hassan.ns.cloudflare.com 2>/dev/null | awk '{print $1}' | sed 's/\.$//')"
    case "$soa" in *cloudflare.com) ok=0 ;; *) ok=1 ;; esac
    row soft "SOA at the zone itself" "hassan.ns.cloudflare.com" "$soa" "$ok"

    ds="$(dig_short DS "$DOMAIN" @1.1.1.1)"
    [ -n "$ds" ] && ok=0 || ok=1
    row soft "DNSSEC (DS at the registry)" "a DS record exists" "$ds" "$ok"
fi
printf '\n'

section "RECORDS"

if [ "$HAVE_DIG" -eq 0 ]; then
    skip_section "record checks need dig"
else
    for name in "$DOMAIN" "$WWW"; do
        ips="$(dig_short A "$name" @1.1.1.1)"
        if all_cf_ips "$ips"; then ok=0; else ok=1; fi
        row critical "$name resolves to" "a Cloudflare proxy address" "$ips" "$ok"
    done

    mx="$(dig_short MX "$DOMAIN" @1.1.1.1)"
    if [ -z "$mx" ]; then mx="none"; ok=0; else ok=1; fi
    row critical "MX records" "none - mail is not used" "$mx" "$ok"

    spf="$(dig +short TXT "$DOMAIN" @1.1.1.1 2>/dev/null | tr -d '"' | grep '^v=spf1' | head -1)"
    [ "$spf" = "v=spf1 -all" ] && ok=0 || ok=1
    row critical "SPF" "v=spf1 -all" "$spf" "$ok"

    dmarc="$(dig +short TXT "_dmarc.$DOMAIN" @1.1.1.1 2>/dev/null | tr -d '"' | head -1)"
    case "$dmarc" in *p=reject*) ok=0 ;; *) ok=1 ;; esac
    row critical "DMARC" "v=DMARC1; p=reject;" "$dmarc" "$ok"

    gv="$(dig_short CNAME "thbwocoajmxu.$DOMAIN" @1.1.1.1)"
    case "$gv" in *googlehosted.com) ok=0 ;; *) ok=1 ;; esac
    row soft "Google verification CNAME" "points at googlehosted.com" "$gv" "$ok"
fi
printf '\n'

section "HTTP"

apex="$(headers "https://$DOMAIN/")"

server_hdr="$(header_value "$apex" server)"
case "$server_hdr" in *cloudflare*) ok=0 ;; *) ok=1 ;; esac
row critical "Edge is serving the apex" "server: cloudflare" "$server_hdr" "$ok"

ray="$(header_value "$apex" cf-ray)"
[ -n "$ray" ] && ok=0 || ok=1
row critical "Cloudflare ray id (PoP)" "present, e.g. ...-FRA" "$ray" "$ok"

altsvc="$(header_value "$apex" alt-svc)"
case "$altsvc" in *h3*) ok=0 ;; *) ok=1 ;; esac
row soft "HTTP/3 offered" 'h3=":443"' "$altsvc" "$ok"

status="$(last_status "$apex")"
[ "$status" = "200" ] && ok=0 || ok=1
row critical "Apex final status" "200" "$status" "$ok"

hsts="$(header_value "$apex" strict-transport-security)"
case "$hsts" in *max-age=31536000*) ok=0 ;; *) ok=1 ;; esac
row critical "HSTS header" "max-age=31536000; includeSubDomains" "$hsts" "$ok"

headers "$ASSET" >/dev/null
sleep 1
second="$(headers "$ASSET")"

cache="$(header_value "$second" cf-cache-status)"
[ "$cache" = "HIT" ] && ok=0 || ok=1
row soft "Static asset cached at the edge" "cf-cache-status: HIT" "$cache" "$ok"

age="$(header_value "$second" age)"
[ -n "$age" ] && ok=0 || ok=1
row soft "Edge age header" "a number of seconds" "$age" "$ok"

www_head="$(headers "https://$WWW/" --no-redirect)"
www_status="$(first_status "$www_head")"
www_loc="$(header_value "$www_head" location)"
ok=1
if [ "$www_status" = "308" ]; then
    case "$www_loc" in "https://$DOMAIN"*) ok=0 ;; esac
fi
row critical "www redirects to apex" "308 -> https://$DOMAIN/" "$www_status $www_loc" "$ok"

plain="$(headers "http://$DOMAIN/" --no-redirect)"
plain_status="$(first_status "$plain")"
case "$plain_status" in 301|308) ok=0 ;; *) ok=1 ;; esac
row critical "Plain HTTP is redirected" "301 or 308" "$plain_status" "$ok"
printf '\n'

printf '  %d of %d checks pass.\n' "$pass_count" "$((pass_count + fail_count))"
if [ "$critical_failed" -ne 0 ]; then
    printf '  %sA critical check failed.%s\n\n' "$RED" "$OFF"
    exit 1
fi
printf '\n'
exit 0
