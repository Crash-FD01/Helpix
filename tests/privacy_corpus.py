# SPDX-FileCopyrightText: 2026 Crash
# SPDX-License-Identifier: GPL-3.0-or-later
"""Casi di prova del filtro privacy: (testo, da nascondere, da lasciare).

Utente «crash» sul PC «crash-desktop». Ogni stringa in «hide» non deve comparire nel risultato; ogni stringa
in «keep» deve restare identica (servono per capire il problema).
"""

CASES = [
    # ---------------------------------------------------------------- file di configurazione
    ('{"username": "admin", "password": "S3gret!", "apiKey": "abc123xyz789"}',
     ["S3gret!", "abc123xyz789"], ['"username": "admin"']),
    ("dbPassword: hunter22\nsmtpPassword=Mail2024!\nadminPwd = Zx9!pp",
     ["hunter22", "Mail2024!", "Zx9!pp"], []),
    ("<configuration><password>XmlPass1</password><user>sa</user></configuration>",
     ["XmlPass1"], ["<user>sa</user>"]),
    ("Server=sql01;Database=erp;User Id=sa;Pwd=ConnStr99;Encrypt=True",
     ["ConnStr99"], ["Server=sql01", "Database=erp"]),
    ("DefaultEndpointsProtocol=https;AccountName=stcliente;AccountKey=bG9uZ2tleWJhc2U2NA==;EndpointSuffix=core.windows.net",
     ["bG9uZ2tleWJhc2U2NA=="], ["AccountName=stcliente"]),
    ("[Interface]\nPrivateKey = yAnz5TF+lXXJte14tji3zlMNq+hd2rYUIgJBgB3fBmk=\nAddress = 10.8.0.2/24\n"
     "[Peer]\nPresharedKey = 7nYp0iGJ3aZ8gEiwUx3KtYyRsKq0BpMvXcZ+1o9hQ6s=\nEndpoint = 93.184.216.34:51820",
     ["yAnz5TF", "7nYp0iGJ", "93.184.216.34"], ["Address = 10.8.0.2/24"]),
    ("client-key-data: LS0tLS1CRUdJTiBSU0EgUFJJVkFURSBLRVktLS0tLQo=\nserver: https://10.0.0.1:6443",
     ["LS0tLS1CRUdJTiBSU0EgUFJJVkFURSBLRVk"], ["server: https://10.0.0.1:6443"]),
    ("wpa_passphrase=CasaMia2024\nssid=CasaMia", ["CasaMia2024"], []),
    ("aws_access_key_id = AK" "IAIOSFODNN7EXAMPLE\naws_secret_access_key = wJ" "alrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
     ["AK" "IAIOSFODNN7EXAMPLE", "wJ" "alrXUtnFEMI"], []),

    # ---------------------------------------------------------------- comandi
    ("nmcli dev wifi connect CasaMia password Wifi!2024", ["Wifi!2024"], ["nmcli dev wifi connect"]),
    ("smbclient //nas/share -U crash%SmbPass1", ["SmbPass1"], []),
    ("docker login -u ci -p DockerPass9 registry.example.com", ["DockerPass9"], ["registry.example.com"]),
    ("echo 'SudoPass!' | sudo -S dnf update", ["SudoPass!"], ["sudo -S dnf update"]),
    ("echo 'mario:NuovaPass1' | chpasswd", ["NuovaPass1"], ["chpasswd"]),
    ("htpasswd -b /etc/nginx/.htpasswd admin WebPass77", ["WebPass77"], ["/etc/nginx/.htpasswd"]),
    ("curl 'https://api.example.com/data?access_token=tok123456789&limit=10'",
     ["tok123456789"], ["limit=10", "api.example.com"]),
    ("https://stcliente.blob.core.windows.net/c/f.zip?sv=2022-11-02&sig=AbC%2Bdef123456%3D",
     ["AbC%2Bdef123456"], ["sv=2022-11-02"]),
    ("git clone https://oauth2:gl" "pat-AbCdEfGhIjKlMnOpQrSt@gitlab.example.com/x.git", ["gl" "pat-AbCd"], []),

    # ---------------------------------------------------------------- token di servizi
    ("STRIPE=sk" "_live_51HabcdefGHIJKLmnopQRst", ["sk" "_live_51Habcdef"], []),
    ("hook https://ho" "oks.slack.com/services/T0001ABCD/B0002EFGH/xYzAbC123dEfGhI456", ["xYzAbC123dEfGhI456"], []),
    ("bot 123456789:A" "AHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw2", ["AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw2"], []),
    ("HF_TOKEN hf" "_abcdefghijklmnopqrstuvwxyzABCDEF", ["hf" "_abcdefghijklmnop"], []),
    ("//registry.npmjs.org/:_authToken=np" "m_abcdefghijklmnopqrstuvwxyz0123456789", ["np" "m_abcdefgh"], []),
    ("SG" ".abcdefghijklmnopqrstuv.abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQ", ["SG" ".abcdefghij"], []),
    ("ya" "29.a0AfH6SMBabcdefghijklmnopqrstuvwxyz", ["ya" "29.a0AfH6"], []),
    ("Cookie: session=abc123; csrftoken=xyz789", ["abc123", "xyz789"], []),

    # ---------------------------------------------------------------- chiavi e hash
    ("-----BE" "GIN PGP PRIVATE KEY BLOCK-----\nlQOYBF...\n-----END PGP PRIVATE KEY BLOCK-----", ["lQOYBF"], []),
    ("-----BE" "GIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAE\nAAAAMwAAAAtzc2gtZW",
     ["b3BlbnNzaC1rZXkt", "AAAAMwAAAAtzc2gtZW"], []),  # chiave tagliata a metà nell'output
    ("-----BEGIN OpenVPN Static key V1-----\ne3a1b2c3d4\n-----END OpenVPN Static key V1-----", ["e3a1b2c3d4"], []),
    ("crash:$6$rounds=5000$saltsalt$K8h3QfG0abcdefghijklmnopqrstuv:19500:0:99999:7:::",
     ["K8h3QfG0abcdef", "saltsalt"], []),
    ("admin:$2y$10$abcdefghijklmnopqrstuuABCDEFGHIJKLMNOPQRSTUVWXYZ0123", ["abcdefghijklmnopqrstuu"], []),

    # ---------------------------------------------------------------- persone e documenti (Italia)
    ("Codice fiscale: RSSMRA80A01H501U", ["RSSMRA80A01H501U"], []),
    ("IBAN IT60 X054 2811 1010 0000 0123 456", ["X054 2811 1010"], []),
    ("IBAN: IT60X0542811101000000123456", ["IT60X0542811101000000123456"], []),
    ("carta 4111 1111 1111 1111 scad 12/27", ["4111 1111 1111 1111"], ["scad 12/27"]),
    ("tel. 0544 123456 - cell: 333 1234567", ["0544 123456", "333 1234567"], []),
    ("telephoneNumber: +39 0544 123456", ["0544 123456"], []),
    ("ls -la /home/mrossi/Documenti /home/crash/Scaricati", ["mrossi", "/home/crash"], ["/Documenti", "/Scaricati"]),

    # ---------------------------------------------------------------- rete (anche Cisco/firewall)
    ("Gi0/1  aabb.ccdd.eeff  DYNAMIC", ["aabb.ccdd.eeff"], ["Gi0/1"]),
    ("ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGabc crash@crash-desktop", ["crash@", "crash-desktop"], ["ssh-ed25519"]),

    # ---------------------------------------------------------------- cose normali da NON toccare
    ("PasswordAuthentication no\nPermitEmptyPasswords no\nPubkeyAuthentication yes", [],
     ["PasswordAuthentication no", "PermitEmptyPasswords no"]),
    ("Accepted password for root from 192.168.1.5 port 22 ssh2", [], ["Accepted password for root"]),
    ("max_tokens=4096 token_count=12 secret_santa=yes", [], ["max_tokens=4096", "token_count=12"]),
    ("docker run -p 8080:80 nginx; ssh -p 2222 host; mysql -h db -P 3306 -p", [],
     ["-p 8080:80", "-p 2222", "-P 3306 -p"]),
    ("PWD=/home/[UTENTE]/progetti OLDPWD=/tmp", [], ["OLDPWD=/tmp"]),
    ("PASS: test_login\nFAIL: test_logout\nkernel: crash dump saved", [], ["PASS: test_login", "kernel: crash dump"]),
    ("UUID=1234abcd-12ab-34cd-56ef-1234567890ab / ext4 defaults 0 1", [],
     ["UUID=1234abcd-12ab-34cd-56ef-1234567890ab"]),
    ("Version 1.2.3 build 20241028 pid 4521 size 1048576 bytes", [], ["1.2.3", "20241028", "1048576"]),
    ("timestamp 1698512345678 duration 0544123456ms", [], ["1698512345678"]),
    ("Timezone: Europe/Rome (CET, +0100)", [], ["+0100"]),
    ("public key: ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQ", [], ["ssh-rsa AAAAB3Nza"]),
    ("Password: \nPassword for crash@crash-desktop:", [], ["Password:"]),
    # falsi positivi trovati facendo passare il filtro su /etc, /var/log e /usr/share/doc
    ("passwd:         files systemd\ngroup:          files systemd", [], ["passwd:         files systemd"]),
    ("Reinstall: base-passwd:amd64 (3.6.3build1), passwd:amd64 (1:4.13+dfsg1-4ubuntu3)", [],
     ["base-passwd:amd64", "passwd:amd64"]),
    ("dpkg: base-passwd: dependency problems, but configuring anyway", [], ["dependency problems"]),
    ("Unpacking imagemagick (8:6.9.12.98+dfsg1-5.2build2) ...\nSetting up lp-solve (5.5.2.5-2ubuntu0.1) ...", [],
     ["6.9.12.98", "5.5.2.5-2ubuntu0.1"]),
    ("locale sd_IN@devanagari.UTF-8 e it_IT.UTF-8", [], ["sd_IN@devanagari.UTF-8"]),
    ("#scopev4 ::ffff:169.254.0.0/112  2\n#label fec0::/10  5", [], ["::ffff:169.254.0.0/112", "fec0::/10"]),
    ("nameserver 8.8.8.8\nnameserver 1.1.1.1\nnameserver 2606:4700:4700::1111", [],
     ["8.8.8.8", "1.1.1.1", "2606:4700:4700::1111"]),
    ("passwd = fallback_getpass(prompt, stream)\ncache_token = $TOKEN_VAR\npassword: {{ vault_db_password }}", [],
     ["fallback_getpass(prompt", "$TOKEN_VAR", "{{ vault_db_password }}"]),
    ("def login(user='', passwd='', acct=''):\n    passwd = ''", [], ["passwd='', acct=''", "passwd = ''"]),
    ("ACL 93.184.216.34-93.184.216.40 allow", ["93.184.216.34", "93.184.216.40"], ["allow"]),
    ("Example: /home/user/file.ext", [], ["/home/user/file.ext"]),
]
