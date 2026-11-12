# The probes: reads only, and nothing on the guest changes. The minion reads its own key with the
# functions salt-call --local runs, called by the minion itself while it renders this file, so the
# probe needs no path to salt-call on either system. The run compares the public key itself with
# the one the master holds for this minion's id; on Salt 3008.5 the two fingerprints differ for the
# same key, so they are recorded and never compared to decide trust (G-980).
{% set own_fingerprint = salt['key.finger']() %}
{% set own_sha256 = salt['key.finger'](hash_type='sha256') %}
{% set hash_type = salt['config.get']('hash_type') %}
{% set pki_dir = salt['config.get']('pki_dir') %}
{% set own_pub = salt['file.read'](pki_dir ~ '/minion.pub') %}
{% set own_pub_head = own_pub.splitlines()[0] if own_pub else 'unread' %}
{% set own_pub_body = own_pub.splitlines()[1:-1] | join('') if own_pub else 'unread' %}
{% set own_pub_lines = own_pub.splitlines() | map('length') | join(',') if own_pub else 'unread' %}
{% set own_pub_file_sha256 = salt['file.get_hash'](pki_dir ~ '/minion.pub', 'sha256') %}

guestcfg-probe-own-fingerprint:
  test.show_notification:
    - text: 'own-fingerprint {{ own_fingerprint }}'

# The same fingerprint with SHA-256 named, the hash type this minion defaults to, and the first line of its public key,
# which names the key's PEM form: what tells a different key from the same key hashed or stored differently.
guestcfg-probe-own-sha256:
  test.show_notification:
    - text: 'own-sha256 {{ own_sha256 }}'

guestcfg-probe-hash-type:
  test.show_notification:
    - text: 'hash-type {{ hash_type }}'

guestcfg-probe-pub-head:
  test.show_notification:
    - text: 'pub-head {{ own_pub_head }}'

# The public key itself, its body joined into one line, and the length of each of its lines: a public key is public,
# and the two tell the same key written in another layout from a different key.
guestcfg-probe-pub-body:
  test.show_notification:
    - text: 'pub-body {{ own_pub_body }}'

guestcfg-probe-pub-lines:
  test.show_notification:
    - text: 'pub-lines {{ own_pub_lines }}'

# SHA-256 of the whole minion.pub file. Salt 3008.5's master fingerprints the whole PEM it holds for an id, where the
# minion's key.finger hashes only the lines between the header and the footer, so the two fingerprints differ for the
# same key; a hash of the whole file is the minion-side read that can match the master's.
guestcfg-probe-pub-file-sha256:
  test.show_notification:
    - text: 'pub-file-sha256 {{ own_pub_file_sha256 }}'

# Where this minion keeps its key pair, as its own configuration resolves it: the directory a key generated on the
# master would be seeded into on this system.
guestcfg-probe-pki-dir:
  test.show_notification:
    - text: 'pki-dir {{ pki_dir }}'
{% if grains['os_family'] == 'Windows' %}

# The sessions signed in on Windows, read with quser. Under the minion service quser reported no
# signed-in user with exit 0 and "No User exists for *" on stderr (G-982); 1 counts as success too.
# The run records the exit, stdout and stderr, and judges on the text.
guestcfg-probe-signed-in-sessions:
  cmd.run:
    - name: quser
    - success_retcodes:
      - 1
{% endif %}
