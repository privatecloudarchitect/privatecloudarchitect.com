# What hostlife.py printed on the reference estate

The run of 2026-10-25T02:28:12Z against three vCenters on VCF 9.1.1, read-only: 67 requests, 61 of them GETs and the
rest the session sign-ins and sign-outs. The terminal showed the estate's own names; below is the same report printed
from the scrubbed record with `python3 hostlife.py --from-record records/hostlife.record.json`, so every vCenter,
cluster and host is a placeholder. The exit code was 1: the ALERT line.

```
$ python3 hostlife.py; echo "exit $?"
hostlife.py: both declarations of every cluster, read 2026-10-25T02:28:12Z

  3 vCenter(s), 5 cluster(s), 11 host(s)

{{vcenter-1}}  vCenter 9.1.1.0 build 25712839
  services   Auto Deploy STOPPED (MANUAL), Image Builder STOPPED (MANUAL), vSphere Lifecycle Manager STARTED (AUTOMATIC), Update Manager STARTED (AUTOMATIC)
  host profiles 0 (read through vi-json); hardware support managers 0
  depot      UMDS none (404); online depots: SDDC Manager's depot 0 of 1 on; added by a user account 1 of 1 on; the VCF depot, through vCenter 0 of 5 on
             46 base image(s), newest 9.1.1.0100.25782009; 16 offline bundle(s)
  {{cluster-1}}  2 host(s)
    image    base 9.1.1.0.25714478; no vendor add-on; no firmware add-on; 0 component(s)
             compliance COMPLIANT, stored 2026-10-06T21:51:52.224Z
    configuration profiles  not enabled

{{vcenter-2}}  vCenter 9.1.1.0 build 25712839
  services   Auto Deploy STOPPED (MANUAL), Image Builder STOPPED (MANUAL), vSphere Lifecycle Manager STARTED (AUTOMATIC), Update Manager STARTED (AUTOMATIC)
  host profiles 0 (read through vi-json); hardware support managers 0
  depot      UMDS none (404); online depots: SDDC Manager's depot 1 of 1 on; added by a user account 1 of 1 on; the VCF depot, through vCenter 0 of 5 on
             47 base image(s), newest 9.1.1.0100.25782009; 24 offline bundle(s)
  {{cluster-2}}  3 host(s)
    image    base 9.1.1.0.25714478; vendor add-on DEL-ESXi 9100.25557999-A03; no firmware add-on; 0 component(s)
             compliance COMPLIANT, stored 2026-10-06T16:15:16.843Z
    configuration profiles  not enabled

{{vcenter-3}}  vCenter 9.1.1.0 build 25712839
  services   Auto Deploy STOPPED (MANUAL), Image Builder STOPPED (MANUAL), vSphere Lifecycle Manager STARTED (AUTOMATIC), Update Manager STARTED (AUTOMATIC)
  host profiles 0 (read through vi-json); hardware support managers 0
  depot      UMDS none (404); online depots: SDDC Manager's depot 1 of 1 on; added by a user account 1 of 1 on; the VCF depot, through vCenter 0 of 5 on
             47 base image(s), newest 9.1.1.0100.25782009; 21 offline bundle(s)
  {{cluster-3}}  2 host(s)
    image    base 9.1.1.0.25714478; no vendor add-on; no firmware add-on; 0 component(s); solutions com.vmware.vsphere-wcp
             compliance COMPLIANT, stored 2026-10-07T18:49:29.566Z
    configuration profiles  not enabled
  {{cluster-4}}  2 host(s)
    image    base 9.1.1.0.25714478; no vendor add-on; no firmware add-on; 0 component(s); solutions com.vmware.vsphere-wcp
             compliance COMPLIANT, stored 2026-10-07T18:55:51.895Z
    configuration profiles  enabled 2026-08-05, last change 2026-08-05; 9 ESX sections, 16 subsections, also nsx; reference host 9.1.0
             compliance NOT_COMPLIANT, stored 2026-10-24T23:43:16.609Z
             {{host-1}}  NON_COMPLIANT
               add    /profile/esx/syslog/global_settings/remote_logging/log_host/0  formatter RFC_5424, framing OCTET_COUNTING, port 514, protocol TCP  [withheld: address]
               delete /profile/esx/syslog/global_settings/remote_logging/log_host/1  formatter RFC_5424, framing OCTET_COUNTING, port 1514, protocol SSL  [withheld: address]
             {{host-2}}  NON_COMPLIANT
               add    /profile/esx/syslog/global_settings/remote_logging/log_host/0  formatter RFC_5424, framing OCTET_COUNTING, port 514, protocol TCP  [withheld: address]
               delete /profile/esx/syslog/global_settings/remote_logging/log_host/1  formatter RFC_5424, framing OCTET_COUNTING, port 1514, protocol SSL  [withheld: address]
  {{cluster-5}}  2 host(s)
    image    base 9.1.1.0.25714478; no vendor add-on; no firmware add-on; 0 component(s); solutions com.vmware.vsphere-wcp
             compliance COMPLIANT, stored 2026-10-07T19:02:48.051Z
    configuration profiles  not enabled

NOTE   {{vcenter-1}}: the depot holds base image 9.1.1.0100.25782009, newer than every image this vCenter's clusters declare
NOTE   {{vcenter-2}}: the depot holds base image 9.1.1.0100.25782009, newer than every image this vCenter's clusters declare
ALERT  {{cluster-4}}: configuration compliance NOT_COMPLIANT, drift at /profile/esx/syslog/global_settings/remote_logging/log_host/0, /profile/esx/syslog/global_settings/remote_logging/log_host/1
NOTE   {{vcenter-3}}: the depot holds base image 9.1.1.0100.25782009, newer than every image this vCenter's clusters declare
exit 1
```

Read each cluster's two lines first, the image and then the configuration. Every compliance line is the result
vCenter stored, with its time; the script starts no check. The drifted items keep their protocol and port and withhold
the address, which is the field that would name a host.

## What --host-builds adds

The run of 2026-10-28T05:08:47Z against the same three vCenters, with `--host-builds` and a key file of the run's own:
89 requests, 83 of them GETs and the rest the session sign-ins and sign-outs. The 22 more GETs than the run above are
one service-versions read and one host list per vCenter, one summary per host, and one read of the last remediation
per image-managed cluster; the depot list adds none, because it keeps what the script already reads. An excerpt,
printed as above from the scrubbed record: each vCenter's lines, and each cluster's heading with its new line.

```
{{vcenter-1}}  vCenter 9.1.1.0 build 25712839
  host builds  2 read live (vi-json), 2026-10-28T05:09:00Z: 2 on 9.1.1 build 25714478
             in maintenance 0; keyed yes; collisions 0; unidentified 0; unread 0
  depot list   46 image(s) with their release dates, read 2026-10-28T05:08:56Z
  {{cluster-1}}  2 host(s)
             last remediation OK, ended 2026-10-06T21:51:24.097Z; failed 0, skipped 0, successful 2
{{vcenter-2}}  vCenter 9.1.1.0 build 25712839
  host builds  3 read live (vi-json), 2026-10-28T05:09:10Z: 3 on 9.1.1 build 25714478
             in maintenance 0; keyed yes; collisions 0; unidentified 0; unread 0
  depot list   47 image(s) with their release dates, read 2026-10-28T05:09:07Z
  {{cluster-2}}  3 host(s)
             last remediation OK, ended 2026-10-06T14:58:20.396Z; failed 0, skipped 0, successful 3
{{vcenter-3}}  vCenter 9.1.1.0 build 25712839
  host builds  6 read live (vi-json), 2026-10-28T05:09:29Z: 6 on 9.1.1 build 25714478
             in maintenance 0; keyed yes; collisions 0; unidentified 0; unread 0
  depot list   47 image(s) with their release dates, read 2026-10-28T05:09:18Z
  {{cluster-3}}  2 host(s)
             last remediation OK, ended 2026-10-06T13:00:07.713Z; failed 0, skipped 0, successful 2
  {{cluster-4}}  2 host(s)
             last remediation unavailable: The last remediation results for entity {{cluster-4}} are unavailable.
  {{cluster-5}}  2 host(s)
             last remediation unavailable: The last remediation results for entity {{cluster-5}} are unavailable.
```

The host builds are what each host runs, read from the host's own summary at the time on the line, not the image
compliance the cluster lines print, which is the result vCenter stored. Every host here is connected, so each build is
what it runs; a host that is not connected would be counted under its last known build and named as such. Zero
collisions is a reading of this estate, not an assumption: a nested or cloned host can report another's hardware UUID,
and such a pair would be counted and never joined. The depot lists differ by one image between the first vCenter and
the other two; every image appears once, with one release date. The last remediation is the one the platform keeps;
two clusters answer that theirs are unavailable, which is recorded as it is said, not read as none ever run. The exit
code is still 1, from the same ALERT line; the flag changes no exit.

## The ordered moves for the chapter's example answers

An estate with a baseline cluster running a Supervisor, host profiles and an ESX upgrade ahead, managed by VCF:

```
$ python3 hostlife.py plan --baselines --supervisor --upgrade --host-profiles --sources
 1. [advised] Feed vSphere Lifecycle Manager from the VCF software depot, which holds its authentication and synchronization in 9.1, and retire UMDS.
      why here: every image is built from what the depot holds; plate 02
      read: What is vSphere Lifecycle Manager <https://techdocs.broadcom.com/us/en/vmware-cis/vsphere/vsphere/9-1/managing-host-and-cluster-lifecycle/about-vsphere-lifecycle-manager-new.html>
      read: The vSphere Lifecycle Manager Depot <https://techdocs.broadcom.com/us/en/vmware-cis/vsphere/vsphere/9-1/managing-host-and-cluster-lifecycle/working-with-vsphere-lifecycle-manager-depots.html>
 2. [documented order] Upgrade NSX Manager and vCenter before any ESX host.
      why here: the ESX upgrade page lists it as a prerequisite; plate 06
      read: Upgrade ESX to 9.1 <https://techdocs.broadcom.com/us/en/vmware-cis/vcf/vcf-9-0-and-later/9-1/deployment/upgrading-cloud-foundation/upgrade-the-management-domain-to-vmware-cloud-foundation-5-2/upgrade-esxi-for-vmware-cloud-foundation-5-2-1.html>
 3. [enforced]  CANNOT BE UNDONE Move every baseline cluster to an image, from the Image Library, a new image or a reference host, after its eligibility check.
      why here: no ESX 9 upgrade until every cluster uses an image; plate 06
      read: Transition a Cluster or a Host That Uses Baselines Into a Cluster or a Host That Uses vSphere Lifecycle Manager Images <https://techdocs.broadcom.com/us/en/vmware-cis/vsphere/vsphere/9-1/managing-host-and-cluster-lifecycle/using-images-to-install-and-update-esxi-hosts-and-clusters/switching-from-baselines-to-images.html>
      read: vSphere Lifecycle Manager Images <https://techdocs.broadcom.com/us/en/vmware-cis/vsphere/vsphere/9-1/managing-host-and-cluster-lifecycle/about-vsphere-lifecycle-manager-new/vlcm-baselines-and-images/vsphere-lifecycle-manager-images.html>
      read: How to Use vSphere Lifecycle Manager Images <https://techdocs.broadcom.com/us/en/vmware-cis/vsphere/vsphere/9-1/managing-host-and-cluster-lifecycle/using-images-to-install-and-update-esxi-hosts-and-clusters.html>
 4. [documented order] In VCF, make that move with SDDC Manager's mechanisms only: its PowerShell script or its API.
      why here: the VCF transition page names the only supported mechanisms; plate 06
      read: Upgrade ESX to 9.1 <https://techdocs.broadcom.com/us/en/vmware-cis/vcf/vcf-9-0-and-later/9-1/deployment/upgrading-cloud-foundation/upgrade-the-management-domain-to-vmware-cloud-foundation-5-2/upgrade-esxi-for-vmware-cloud-foundation-5-2-1.html>
      read: Transitioning from vSphere Lifecycle Manager Baselines to vSphere Lifecycle Manager Images <https://techdocs.broadcom.com/us/en/vmware-cis/vcf/vcf-9-0-and-later/9-1/deployment/upgrading-cloud-foundation/upgrade-the-management-domain-to-vmware-cloud-foundation-5-2/vlcm-baseline-to-vlcm-image-cluster-transition-.html>
 5. [documented order] With a Supervisor on a baseline cluster, move that cluster after the vCenter upgrade and before the ESX upgrade.
      why here: the VCF transition page orders it; plate 06
      read: Transitioning from vSphere Lifecycle Manager Baselines to vSphere Lifecycle Manager Images <https://techdocs.broadcom.com/us/en/vmware-cis/vcf/vcf-9-0-and-later/9-1/deployment/upgrading-cloud-foundation/upgrade-the-management-domain-to-vmware-cloud-foundation-5-2/vlcm-baseline-to-vlcm-image-cluster-transition-.html>
 6. [advised] Without a hardware support manager, vSphere Lifecycle Manager treats the firmware a host runs as its target: keep firmware current by the vendor's own process.
      why here: nothing in the image will move it; plate 01
      read: Firmware Updates with vSphere Lifecycle Manager <https://techdocs.broadcom.com/us/en/vmware-cis/vsphere/vsphere/9-1/managing-host-and-cluster-lifecycle/using-images-to-install-and-update-esxi-hosts-and-clusters/firmware-updates.html>
 7. [documented order] Import the target image into the VCF instance through VCF Operations, at the ESX version of the release's bill of materials.
      why here: a cluster in VCF takes its image from the instance; plate 02
      read: Managing vSphere Lifecycle Manager Images for VMware Cloud Foundation <https://techdocs.broadcom.com/us/en/vmware-cis/vcf/vcf-9-0-and-later/9-1/lifecycle-management/lifecycle-management-of-vcf-components/managing-vsphere-lifecycle-manager-images-for-vmware-cloud-foundation.html>
      read: Import a vSphere Lifecycle Manager Image to a VCF Instance <https://techdocs.broadcom.com/us/en/vmware-cis/vcf/vcf-9-0-and-later/9-1/lifecycle-management/lifecycle-management-of-vcf-components/managing-vsphere-lifecycle-manager-images-for-vmware-cloud-foundation/import-a-vsphere-lifecycle-manager-image-to-a-vcf-instance.html>
 8. [documented order] Upgrade ESX by remediating each cluster to its new image: precheck, stage, then remediate.
      why here: the image is the only way to upgrade ESX in 9.x; plate 06
      read: vSphere Lifecycle Manager Images and Baselines <https://techdocs.broadcom.com/us/en/vmware-cis/vsphere/vsphere/9-1/managing-host-and-cluster-lifecycle/about-vsphere-lifecycle-manager-new/vlcm-baselines-and-images.html>
      read: Lifecycle Management of Clusters and Standalone Hosts at Scale <https://techdocs.broadcom.com/us/en/vmware-cis/vsphere/vsphere/9-1/managing-host-and-cluster-lifecycle/global-lifecycle-mangement.html>
      read: Staging vSphere Lifecycle Manager Images to ESX Hosts in a Cluster or Standalone Hosts <https://techdocs.broadcom.com/us/en/vmware-cis/vsphere/vsphere/9-1/managing-host-and-cluster-lifecycle/using-images-to-install-and-update-esxi-hosts-and-clusters/staging-vlcm-images-to-esxi-hosts-in-a-cluster.html>
      read: Upgrade ESX to 9.1 <https://techdocs.broadcom.com/us/en/vmware-cis/vcf/vcf-9-0-and-later/9-1/deployment/upgrading-cloud-foundation/upgrade-the-management-domain-to-vmware-cloud-foundation-5-2/upgrade-esxi-for-vmware-cloud-foundation-5-2-1.html>
 9. [advised] Build each VCF host from an ESX ISO, the one exported from its cluster's image where it needs a custom one, and keep stateless hosts out of VCF.
      why here: VCF host preparation documents the ISO and supports no stateless host; plate 03
      read: Managing ESX Hosts in VMware Cloud Foundation <https://techdocs.broadcom.com/us/en/vmware-cis/vcf/vcf-9-0-and-later/9-1/building-your-private-cloud-infrastructure/host-management.html>
      read: Install ESX on Hosts Using an ISO Image <https://techdocs.broadcom.com/us/en/vmware-cis/vcf/vcf-9-0-and-later/9-1/deployment/deploying-a-new-vmware-cloud-foundation-or-vmware-vsphere-foundation-private-cloud-/preparing-your-environment/preparing-esx-hosts-for-vmware-cloud-foundation-or-vmware-vsphere-foundation/install-esx-on-hosts-using-the-iso.html>
      read: Creating a Custom ESX ISO Image Using vSphere Lifecycle Manager <https://techdocs.broadcom.com/us/en/vmware-cis/vcf/vcf-9-0-and-later/9-1/deployment/deploying-a-new-vmware-cloud-foundation-or-vmware-vsphere-foundation-private-cloud-/preparing-your-environment/preparing-esx-hosts-for-vmware-cloud-foundation-or-vmware-vsphere-foundation/create-a-custom-esx-iso-image-using-vsphere-lifecycle-manager.html>
10. [documented order]  CANNOT BE UNDONE Move the cluster from host profiles to Configuration Profiles: eligibility, import from a reference host or a JSON file, validate, precheck, remediate.
      why here: on an image cluster every host must first be compliant with the image; plate 05
      read: What is vSphere Configuration Profiles <https://techdocs.broadcom.com/us/en/vmware-cis/vsphere/vsphere/9-1/vsphere-configuration-profiles/using-vsphere-config-profiles-to-manage-host-configuration-at-a-cluster-level.html>
      read: Enable vSphere Configuration Profiles on an Existing Cluster <https://techdocs.broadcom.com/us/en/vmware-cis/vsphere/vsphere/9-1/vsphere-configuration-profiles/enable-vsphere-configuration-profiles-on-a-cluster/transition-to-using-vsphere-configuration-profiles.html>
      read: How Host Profile Configuration Settings Map to the vSphere Configuration Profiles Settings for ESX Hosts <https://techdocs.broadcom.com/us/en/vmware-cis/vsphere/vsphere/9-1/vsphere-configuration-profiles/view-host-settings-and-host-overrides/how-host-profile-configuration-settings-map-to-the-vsphere-configuration-profile-settings-for-esx-hosts.html>
11. [advised] Before you declare a setting, find every other writer of it and leave out what another system owns.
      why here: remediation writes the declared value back over the other writer's; plate 05
      read: What is vSphere Configuration Profiles <https://techdocs.broadcom.com/us/en/vmware-cis/vsphere/vsphere/9-1/vsphere-configuration-profiles/using-vsphere-config-profiles-to-manage-host-configuration-at-a-cluster-level.html>
      read: Check Host Compliance Against the Desired Configuration for the Cluster <https://techdocs.broadcom.com/us/en/vmware-cis/vsphere/vsphere/9-1/vsphere-configuration-profiles/check-compliance.html>
12. [advised] Read both declarations on a schedule: vCenter holds the compliance and remediates, VCF Operations detects fleet drift and does not remediate.
      why here: drift is only a finding when someone reads it; plate 05
      read: Check Host Compliance Against the Desired Configuration for the Cluster <https://techdocs.broadcom.com/us/en/vmware-cis/vsphere/vsphere/9-1/vsphere-configuration-profiles/check-compliance.html>
      read: What's new: VCF Operations <https://techdocs.broadcom.com/us/en/vmware-cis/vcf/vcf-9-0-and-later/9-1/release-notes/vmware-cloud-foundation-9-1-0-0-release-notes/what-s-new/whats-new-vcf-ops.html>
      read: Fleet Configuration Management <https://techdocs.broadcom.com/us/en/vmware-cis/vcf/vcf-9-0-and-later/9-1/design/design-blueprints-for/infrastructure-modernization/fleet-management-blueprint/vsphere-configuration-management.html>
```
