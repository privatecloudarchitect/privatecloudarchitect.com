# The baseline: one managed file, the same state on Linux and on Windows. The first apply
# creates it, the next finds it correct and changes nothing, and an apply after a local
# change puts it back. Only the path depends on the operating system.
{% set managed_file = 'C:\\ProgramData\\guestcfg\\managed.conf' if grains['os_family'] == 'Windows' else '/etc/guestcfg/managed.conf' %}

guestcfg-managed-file:
  file.managed:
    - name: {{ managed_file }}
    - makedirs: True
    - contents: |
        managed-by: salt
        baseline: guest-configuration
