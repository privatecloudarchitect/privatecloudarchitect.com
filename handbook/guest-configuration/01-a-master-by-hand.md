# A Salt master, by hand: a VM you declare, an API you reach over TLS

[00-before-you-start](./00-before-you-start.md) said which Salt this is and what you need. This page builds the master:
you generate its API's certificate and an API password, fill one template, apply it, and prove two things. The API
answers over TLS to an account that can do only what you listed, and you can sign in to the master and run `salt-key`.
Most of the page is one wait, for the master's first boot.

## The one idea

A Salt master is not special infrastructure. It is a VM like stage 02's, whose cloud-init installs Salt instead of
nginx. What makes it a good master is what you write into its configuration before it boots:

- **Salt 3008 LTS, pinned,** so a routine `apt upgrade` cannot move it to another release.
- **The API on TLS,** with a certificate you made, never `disable_ssl: true`.
- **An API account with a list of rights,** never `.*`: exactly the functions a caller needs, on exactly the minions
  you name.
- **No automatic key acceptance.** Salt's defaults, `auto_accept: False` and `open_mode: False`, stay.

The template [`templates/02x-vm-salt-minion/salt-master.vm.yaml`](./templates/02x-vm-salt-minion/salt-master.vm.yaml)
carries all four; read its comments as you fill it.

## Step 1: make the API's certificate and its password

In an empty working folder that only you can read:

```bash
mkdir -m 700 salt-lessons && cd salt-lessons
openssl req -x509 -newkey rsa:2048 -nodes -days 365 -subj /CN=salt-master -keyout api.key -out api.crt
( umask 077; openssl rand -base64 24 | tr -d '\n' > api.password )
printf '%s' "$(cat api.password)" | sha256sum      # macOS: shasum -a 256
```

```
<64 hexadecimal characters>  -
```

The certificate's name is `salt-master`, and you will connect to it by that name (step 5). The template stores only
the password's **digest**; the password itself never leaves your workstation.

## Step 2: fill the template

Copy `salt-master.vm.yaml` beside these files as `master.yaml` and fill its `<REPLACE_ME-...>` values:

| Placeholder | Fill with |
|---|---|
| `<REPLACE_ME-ubuntu-24.04-image>` | the Ubuntu image's display name from page 00, such as `ubuntu-24.04.3-LTS` |
| `<REPLACE_ME-storage-class>` | your storage class |
| `<REPLACE_ME-your-ssh-public-key>` | the one line of `~/.ssh/id_ed25519.pub` |
| `<REPLACE_ME-linux-minion-id>`, `<REPLACE_ME-windows-minion-id>` | `salt-minion-linux` and `salt-minion-win`, the names of the minions pages 02 and 05 build |
| `<REPLACE_ME-sha256-of-api-password>` | the digest from step 1 |
| `<REPLACE_ME-tls-certificate-pem>`, `<REPLACE_ME-tls-private-key-pem>` | the contents of `api.crt` and `api.key` |

**Paste a PEM at its placeholder's indentation.** Each line of the certificate and the key goes at the same column as
the placeholder it replaces; a line that starts further left ends the YAML block, and the master boots without its
certificate. The filled file holds the API's private key, so keep it with the others: `chmod 600 master.yaml`.

The minion ids matter now, before any minion exists: the API account's rights name them (`L@salt-minion-linux,salt-minion-win`).
A master that minions join for years grows that list by editing its configuration as each one joins.

## Step 3: a front door for the lessons

The master sits on your namespace's private network, which your workstation cannot reach. The template gives the API
a load balancer on port 8000. For these lessons, add one more for SSH, as its own file `ssh-front-door.yaml`:

```yaml
# For the walkthrough's lessons only: a way in to the master over SSH. Delete it with
# everything else in walkthrough 06; do not leave port 22 on a load balancer.
apiVersion: vmoperator.vmware.com/v1alpha5
kind: VirtualMachineService
metadata:
  name: salt-master-ssh
  labels:
    app.kubernetes.io/name: salt-master-ssh
    app.kubernetes.io/part-of: guest-configuration
spec:
  type: LoadBalancer
  selector:
    app: salt-master
  ports:
    - name: ssh
      protocol: TCP
      port: 22
      targetPort: 22
```

## Step 4: prove it, then build it

```bash
kubectl apply -f master.yaml --dry-run=server
```

```
secret/salt-master-bootstrap created (server dry run)
virtualmachine.vmoperator.vmware.com/salt-master created (server dry run)
virtualmachineservice.vmoperator.vmware.com/salt-api created (server dry run)
```

```bash
kubectl apply -f master.yaml
kubectl apply -f ssh-front-door.yaml
kubectl get vm salt-master -o jsonpath='{.status.powerState}{"  "}{.status.network.primaryIP4}{"\n"}'
kubectl get virtualmachineservice
kubectl get vmservice salt-api -o jsonpath='{.status.loadBalancer.ingress[0].ip}{"\n"}'
kubectl get vmservice salt-master-ssh -o jsonpath='{.status.loadBalancer.ingress[0].ip}{"\n"}'
```

What they printed on the reference estate, 2026-11-12, with documentation addresses in place of its own:

```
secret/salt-master-bootstrap created
virtualmachine.vmoperator.vmware.com/salt-master created
virtualmachineservice.vmoperator.vmware.com/salt-api created
virtualmachineservice.vmoperator.vmware.com/salt-master-ssh created
PoweredOn  192.0.2.66
NAME              TYPE           AGE
salt-api          LoadBalancer   51s
salt-master-ssh   LoadBalancer   50s
198.51.100.24
198.51.100.26
```

The machine takes its address first. Its first boot then installs Salt from Broadcom's package location and starts
the API, and until that is done step 5's sign-in is refused or times out: read again every half-minute. The harness
gives a master's first boot 30 minutes before it calls the build failed. Note the three addresses: the master's own
(`192.0.2.66` here) is what every minion is given; the other two are your ways in.

## Step 5: sign in to the API, over TLS, as the narrow account

```bash
API=198.51.100.24      # yours: salt-api's address
curl -sS --cacert api.crt --resolve salt-master:8000:$API https://salt-master:8000/login \
  -H 'Accept: application/json' -d username=guestcfg-api -d eauth=file \
  --data-urlencode "password=$(cat api.password)"
```

What it printed, the five fields the proof kept of the answer's one item, on fewer lines, the token cut short:

```json
{"eauth": "file", "user": "guestcfg-api", "expire": 1794517811.8035092,
 "perms": [{"@runner": ["jobs.lookup_jid"]},
           {"@wheel": ["key.list_all", "key.accept", "key.delete", "key.finger", "key.print"]},
           {"L@salt-minion-linux,salt-minion-win": ["test.ping", "grains.item", "state.apply"]}],
 "token": "45fdf9…"}
```

`--cacert api.crt` trusts exactly the certificate you made, and `--resolve` connects to the load balancer's address
under the certificate's name, so TLS is verified rather than switched off. The answer lists the account's whole
reach: six key and job functions, and three Salt functions on two named minions. Nothing else, ever, through this API.

## Step 6: sign in to the master

```bash
ssh salt-operator@198.51.100.26 'salt-master --version; sudo salt-key -L'
```

```
Warning: Permanently added '198.51.100.26' (ED25519) to the list of known hosts.
salt-master 3008.5 (Argon)
Accepted Keys:
Denied Keys:
Unaccepted Keys:
Rejected Keys:
```

The warning is SSH meeting the master for the first time. A running master, the pinned release, and no key of any kind. Every key that ever appears here will be one you
decided to accept.

## Two things that will bite you

**`Permission denied (publickey,password)` on a machine that otherwise built.** The login account is called
`salt-operator` because Ubuntu's base system already has a group named `operator`: cloud-init cannot create a user of
that name, records the failure only in its own log, and finishes everything else. If you rename the account, give it a prefix;
when a key login is refused on a machine whose first boot otherwise ran, check that the account exists before
suspecting the key (G-905).

**`curl: (60) SSL: no alternative certificate subject name matches`.** You connected by address to a certificate made
for the name `salt-master`. Keep `--resolve salt-master:8000:<address>`; do not reach for `-k`, which turns off the one
check that tells you the API is yours.

## What you just did, and where it goes

| You did | The template has | What a blueprint adds (page 07) |
|---|---|---|
| made a certificate and a password digest | both as cloud-config files | the same, as inputs, each one encrypted |
| named the minion ids the API may reach | `L@<linux-id>,<windows-id>` | an input listing the ids |
| applied the master and a load balancer | a Secret, a VirtualMachine, a VirtualMachineService | a catalog form, a deployment record |
| signed in to the API and to the master | the narrow account; the optional `salt-operator` login | no login: a master no one signs in to |

## Next

[`02-one-minion-and-its-key.md`](./02-one-minion-and-its-key.md): build one Linux minion, watch its key arrive, and
decide whether to trust it.
