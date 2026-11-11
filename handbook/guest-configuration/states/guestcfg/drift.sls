# The drift for step 6: the same file, changed outside the baseline. It goes through a
# state because the run's API account holds only the state.apply right, no file-write
# right; a real change arrives another way, and the baseline answers it the same.
{% set managed_file = 'C:\\ProgramData\\guestcfg\\managed.conf' if grains['os_family'] == 'Windows' else '/etc/guestcfg/managed.conf' %}

guestcfg-managed-file-drift:
  file.managed:
    - name: {{ managed_file }}
    - contents: |
        managed-by: someone-else
