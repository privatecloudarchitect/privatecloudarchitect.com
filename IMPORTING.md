# Importing super metrics, views and dashboards in the VCF Operations UI

Some folders here ship VCF Operations content: super metrics, views and a dashboard that reads them. This page takes
you from the download to a dashboard showing data, using only the VCF Operations UI. Every screen, option and default
below was read on VCF Operations 9.1.1 on 2026-10-09, and each super metric import route was run end to end with a
throwaway super metric that was deleted afterwards.

## What you download

Each piece of content is its own file. A dashboard zip does not carry the super metrics or the views it reads, so
you import all of a folder's files, in order. Take the whole repository with GitHub's **Code**, **Download ZIP** and
unzip that on your machine, or open a single file on GitHub and use **Download raw file**. Do not unzip the content
files themselves: each `.zip` is exactly what an import screen expects.

| File in a folder | What it is | The screen that takes it |
|---|---|---|
| `supermetrics/*.contentpkg.zip` | the folder's super metrics as a content package | Content Management, Import |
| `supermetrics/*.import.json` | the same super metrics as one readable JSON file | Super Metrics, Import (the alternative) |
| `views/*.contentpkg.zip` | the folder's views as a content package | Content Management, Import |
| `views/*.import.zip` | the views in the shape the Views screen takes | Views, Manage, Import |
| `dashboard/*.import.zip` | the dashboard | Dashboards, Manage, Import |

## The order, and why it matters

Super metrics first, then views, then the dashboard, then switch the super metrics on in a policy. A view finds each
super metric by its id, and the dashboard finds each view by its id. The import screens below keep the ids the files
ship with, which is what keeps those references intact on your instance.

## 1. Super metrics

**Content Management, the recommended route, because the same screen then takes the views.**

1. In the top bar click **Operate**, then in the left pane **Administration**, **Control Panel**, and the
   **Content Management** tile. Open the **Import** tab.
2. Click **BROWSE** and choose the folder's `supermetrics/*.contentpkg.zip`.
3. Under **In case of conflict**, choose **Skip item(s)**. The default, **Overwrite existing content**, replaces a
   super metric that already exists with the same id, including any value you changed in it since, such as a price.
4. Click **IMPORT**. The results table reads **Super Metrics**, with the total, how many were imported, how many
   were skipped because they were already there, and **Failed 0**.

**The alternative: the Super Metrics screen.** Under **Administration**, open **Configurations** and the **Super
Metrics** tile. Click the **⋯** beside **ADD**, then **Import**, choose the folder's `supermetrics/*.import.json`,
leave **Skip import** selected (the default here) and click **IMPORT**. The dialog reports how many were imported and
skipped.

Either route keeps each super metric's id and assigns it to its object types: select one on the Super Metrics screen
and its details show **Assigned Object Types**. Neither switches it on: the same details show **Policies Enabled (0)**,
which is step 4.

## 2. Views

- A folder that ships `views/*.contentpkg.zip`: the **Content Management**, **Import** tab again, with **Skip item(s)**.
- A folder that ships `views/*.import.zip`: **Operate**, **Dashboards**, then **Views** and **Manage** in the panel
  beside the menu. Click **⋯**, **Import**, choose the zip, keep **Skip import** (the default) and click **IMPORT**.

## 3. The dashboard

**Operate**, **Dashboards**, then **Manage** in the panel beside the menu. Click **⋯**, **Import**, and choose the
folder's `dashboard/*.import.zip` as it is. **In case of a conflict** defaults to **Rename**, which keeps a dashboard
of the same name that you already have and adds this one beside it; **Overwrite** replaces it. You own the dashboard
you import. Import it after the views: if you imported it first, import the views now, then import the dashboard again
with **Overwrite**.

## 4. Switch the super metrics on in a policy

An imported super metric collects nothing until it is enabled in the policy that governs the objects it is assigned
to, and nothing reports the gap: its columns simply stay blank. The policy is the one applied to the hosts, clusters or
VMs you want covered; if you have created no policies of your own, it is the **Default Policy**.

- **One at a time.** On the **Super Metrics** screen, select the super metric and click **EDIT**. The editor has four
  steps; open **4 - Policies**, tick the policy in the column for each object type the super metric is assigned to, and
  click **UPDATE**.
- **Several at once.** Under **Administration**, **Configurations**, open the **Policy Definition** tile, select the
  policy and click **Edit Policy**, then **Metrics and Properties**. Filter by object type, select the super metrics,
  choose **Activate**, and save the policy.

## 5. Wait, then read the dashboard

The editor's Policies step says it plainly: after one collection cycle the super metric begins collecting, and it
appears on each object of its type. Collection runs every five minutes by default, so give it two cycles before you
judge. A dashboard whose rows stay blank after that is almost always step 4.

## If something looks wrong

- **Failed above zero in the results table.** VMware's 9.1 page on importing super metrics notes that an import fails
  when the file refers to an object that does not exist on the target instance; check the folder's README for what the
  content expects to find.
- **Blank columns or tiles.** The super metrics are not switched on in the policy that governs those objects (step 4),
  or not enough collection cycles have passed (step 5).
- **You want a newer version of the files.** Import with **Overwrite existing content** only when you want the shipped
  version to replace what is on your instance, including any value you edited; otherwise keep **Skip item(s)** and
  make the change in the editor.

## Where these steps come from

Read in VMware's documentation for VCF 9.1: the Super Metrics tab, exporting and importing a super metric, and the
policy workspace's Metrics and Properties page on techdocs.broadcom.com, and Broadcom knowledge base article 445394 for
the Content Management path. The screens, the defaults, the id each route keeps, the assigned object types, the policy
count and what **Overwrite** and **Skip** do to a super metric that already exists were read on a VCF Operations 9.1.1
instance on 2026-10-09. The views and dashboard import dialogs were opened and closed on that instance without
importing anything; each folder's view package was test-imported through the content API before it was published, on the date its README gives.
