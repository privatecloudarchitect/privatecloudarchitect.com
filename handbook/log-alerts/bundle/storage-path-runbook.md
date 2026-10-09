# Storage path health: what to do when an alert fires

What to do for each alert in `storage-path-health.json`; each alert's description names its section here. The
chapter that explains how the alerts were built, and why each step relies on the platform behaviour it does, is
privatecloudarchitect.com/handbook/log-alerts.

**First, for every alert.** vSphere HA VM Component Protection is the platform's response to device loss and all
paths down on a cluster where it is configured; these alerts arrive minutes after the event. Check what it already did
(the cluster's `com.vmware.vc.HA.Vmcp*` events) before acting, and do not evacuate a host from a log alert.

To read the evidence, search Log Management for the host over the alert's window with two filters at a time:
`vc_event_type` exists (vCenter's events about the host) and `appname` is `vobd` (the host's own storage
observations). An event that arrived on only one channel is still real; the other channel may have been dark.

## sp-01

**Storage device permanently lost (PDL).** The array reported the device gone on all paths.

1. Identify the device and the datastores from the host's `vobd` record (`Device ... has been removed or is
   permanently inaccessible`) or from vCenter's event.
2. Confirm with the array team whether the removal was planned. A planned removal follows the documented sequence
   (migrate, unmount, detach), and a PDL during one means a step was skipped.
3. VMs on the device: VMCP powers off and restarts them where configured ("Power off and restart VMs"); otherwise
   power them off and restart them on hosts that see healthy storage.
4. When no handles remain, ESX removes the device (`Disk.AutoremoveOnPDL`); rescan after the array side is resolved.

## sp-02

**All paths down started.** No path answers and no PDL code arrived. Many APD episodes end within the 140-second
timer, which is ESX's default.

1. Read the identifier in the record: a filesystem identifier for NFS and VMFS datastores, a device name for a LUN.
2. Wait for the exit record (`esx.clear.storage.apd.exit`, `vob.storage.apd.exit`). If SP-03 follows, go there.
3. If several hosts report APD on the same datastore in one window, treat it as an array or fabric event and call
   the storage team.

## sp-03

**All paths down timeout.** The timer expired: the host now fails non-VM I/O fast while VM I/O keeps retrying.
I/O resumes on its own if paths return.

1. Engage the storage and fabric teams now: the device is unreachable from this host on every path.
2. Check VMCP's APD response on the cluster (conservative or aggressive restart, or events only).
3. Watch for the host losing its connection to vCenter (SP-C2).

## sp-04

**Storage paths dead.** One or more paths changed state to dead; the device may still be reachable on others.

1. Read the path names (`vmhbaN:C:T:L`) in the records (`scsiPath` for SCSI devices, `storagePath` for devices the
   psastor stack claims) and group them by HBA: paths through one HBA point to that HBA, its cable or its switch port;
   paths through every HBA point to the array.
2. Compare the HBA numbers with the site's record of which HBA cables to which fabric.
3. Host reboots log paths coming back "changed state from dead"; dead paths during a host's maintenance window are
   expected.

## sp-05

**Path redundancy degraded, or connectivity lost.** Degraded: the device runs on fewer paths than configured.
Connectivity lost: no path remains (critical).

1. For degraded, as SP-04.
2. For connectivity lost, as SP-03; expect APD records to follow or accompany it.

## sp-06

**Datastore access lost.** VMFS heartbeat timed out ("Lost access to volume ... Recovery attempt is in progress"),
recovery failed (`unrecoverable`, critical), or the NFS server disconnected ("Lost connection to server ... mount point
...", critical).

1. Read the volume or the NFS server and mount point from the event.
2. A timed-out heartbeat usually recovers on its own (`esx.problem.vmfs.heartbeat.recovered`); if it does not, treat
   it as SP-03 for that volume.
3. For NFS, check the server and the network path from the host's NFS vmknic. A host reboot logs
   `esx.clear.vmfs.nfs.server.restored` as its mounts come back, so read the host's state before the event.

## sp-07

**Frequent power-on resets** on a device or a path ("Frequent PowerOn Reset Unit Attentions are occurring on device
..."). The array or a fabric component is resetting.

1. Read the device or path from the event and ask the array team whether the controller or port restarted.
2. The host's own `vob.scsi.scsipath.por` records, one per reset, show the cadence. Single resets are common on some
   local devices and do not reach this event; the event marks a frequency ESX itself judged abnormal.

## sp-08

**Host-side SCSI command failures.** `H:0x1` (no connect): the host could not reach the LUN; `H:0x3` (timed out): a
command in flight timed out; `H:0x8` (reset): the bus or the device was reset, or the HBA driver aborted I/O. `H:0x0`
is no host-side error and is never an alert. Above 4 in 5 minutes warns; above 10 `H:0x1` is critical.

1. Read the device (`to dev "..."`) and the path from the records; a single device points to the array or its zoning, a
   single HBA points to the host side.
2. `H:0x1` alone is not a PDL; PDL needs the array's sense codes on every path.

## sp-c1

**Host at risk of hanging.** A device is lost or timed out and commands keep failing on the same host.

1. Confirm VMCP acted on the affected VMs.
2. Identify the device and engage the array team.
3. If the host stops responding to vCenter (SP-C2), follow the host recovery procedure; do not reboot a host while the
   array side is still failing unless VMCP has already restarted its VMs elsewhere.

## sp-c2

**Host lost to vCenter after storage symptoms.** The host stopped answering vCenter after APD began or timed out.

1. The host's own syslog may still arrive while vCenter cannot reach it (or the reverse): read both channels.
2. Proceed as SP-03, and check HA's host failure response on the cluster.

## sp-c3

**Zoning or optics signature.** Lost connections and failing paths together on one host.

1. Check the zone set for the host's initiators and the optics on the switch ports serving it.
2. Compare with the other hosts in the cluster: one host points to its own ports; several point to a shared zone.
