# What a run looks like

The reference estate, 2026-10-12 (UTC), four throwaway organizations: an All Apps and a classic organization over
OIDC, and one of each over SAML, all federated to one Entra ID tenant. Run with `--redact`, so the names are
placeholders. Exit 1: warnings, nothing broken now.

```
$ ORGS=<the four organizations> python3 watch.py --redact
{{org-1}}  (oidc, all-apps)
  WARN    key_refresh     refresh every 24 h: an emergency roll at the provider stops sign-in for up to that long; set 1 h
  OK      keys_held       all 6 published keys are held
  OK      pkce            PKCE is off
  WARN    secret_end      the secret the organization holds ends in 26.0 days: rotate with overlap
  OK      app_gate        the app is enabled and requires assignment
  OK      group_names     every imported group (1) is assigned to the app by that name
  OK      break_glass     1 enabled local user(s) holding Organization Administrator

{{org-2}}  (saml, all-apps)
  OK      saml_cert_end   the active signing certificate ends in 361.0 days
  OK      saml_cert_held  the organization's metadata holds every signing certificate on the app
  OK      app_gate        the app is enabled and requires assignment
  OK      group_names     every imported group (1) is assigned to the app by that name
  WARN    break_glass     no enabled local user holds Organization Administrator: when the provider refuses the organization, nobody can sign in to it

{{org-3}}  (oidc, classic)
  WARN    key_refresh     refresh every 24 h: an emergency roll at the provider stops sign-in for up to that long; set 1 h
  OK      keys_held       all 6 published keys are held
  OK      pkce            PKCE is off
  WARN    secret_end      the secret the organization holds ends in 23.2 days: rotate with overlap; 1 other listed secret(s) already expired
  OK      app_gate        the app is enabled and requires assignment
  OK      group_names     every imported group (1) is assigned to the app by that name
  WARN    break_glass     no enabled local user holds Organization Owner: when the provider refuses the organization, nobody can sign in to it

{{org-4}}  (saml, classic)
  OK      saml_cert_end   the active signing certificate ends in 358.2 days
  WARN    saml_cert_held  1 other signing certificate(s) on the app are not in the organization's metadata: making one active stops sign-in until metadata carrying it is loaded
  OK      app_gate        the app is enabled and requires assignment
  OK      group_names     every imported group (1) is assigned to the app by that name
  WARN    break_glass     no enabled local user holds Organization Owner: when the provider refuses the organization, nobody can sign in to it

4 organization(s); exit 1; record written with every estate value replaced
```

## What to read in it

- **`key_refresh` warns on both OIDC organizations.** They refresh Entra's keys every 24 hours, the interval they
  were built with. Every key Entra publishes is held today (`keys_held`), so sign-in works; but when Entra rolls a
  key in an emergency, sign-in stops until the next refresh, which on this setting can be a day away. The chapter's
  practice is one hour with strategy ADD. The run was taken minutes after an hourly refresh attempt that left one
  organization's last success a full day old; that is on schedule (the refresh waits until a full interval has
  passed, and the next hourly run did refresh it), so the check warns on the interval and does not fail on the age.
- **`secret_end` names the secret the organization holds,** matched by Graph's hint, not the one that ends last.
  `{{org-3}}` lists two secrets: one ends in 23 days and is the one it uses; the other expired six days before the
  run and is unused, so it is reported, not judged.
- **`saml_cert_held` warns on `{{org-4}}`.** Its Entra app carries a second signing certificate that the
  organization's metadata does not hold. Nothing fails while the first stays active; made active, the second
  stops every sign-in until metadata carrying it is loaded. The warning is the step the rollover needs first.
- **`break_glass` warns on three of the four, judged by each organization's own top role.** An All Apps
  organization's is Organization Administrator, a classic one's Organization Owner, read from the organization's
  role list. Only `{{org-1}}` keeps a local user holding it, so on the other three a refusal at Entra (a disabled
  app, a blocked service principal) leaves nobody able to sign in.
- **Nothing failed.** On your estate a `fail` is the line to act on today: a published key not held, refreshes not
  succeeding, an expired secret or certificate, a renamed group, PKCE on, or a disabled app.
