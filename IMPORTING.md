# Importing super metrics, views and dashboards in the VCF Operations UI

Some folders here ship VCF Operations content: super metrics, views and a dashboard that reads them. This page takes
you from the download to a dashboard showing data, using only the VCF Operations UI. Every screen, option and default
below was read on VCF Operations 9.1.1 on 2026-10-09, and each route this page recommends was run there, with
throwaway super metrics and a throwaway view that were deleted afterwards.

## What you download

Each piece of content is its own file. A dashboard zip does not carry the super metrics or the views it reads, so
you import all of a folder's files, in order. Take the whole repository with GitHub's **Code**, **Download ZIP** and
unzip that on your machine, or open a single file on GitHub and use **Download raw file**. Do not unzip the content
files themselves: each `.zip` is exactly what an import screen expects.

| File in a folder | What it is | The screen that takes it |
|---|---|---|
| `supermetrics/*.import.json` | the folder's super metrics, one readable JSON file | Super Metrics, Import |
| `views/*.import.zip` | the folder's views | Views, Manage, Import |
| `dashboard/*.import.zip` | the dashboard | Dashboards, Manage, Import |
| `*/*.contentpkg.zip` | the same super metrics or views as content packages | Content Management, Import (bulk route, below) |

## The order, and why it matters

Super metrics first, then views, then the dashboard, then switch the super metrics on in a policy. A view finds each
super metric by its id, and the dashboard finds each view by its id. The import screens keep the ids the files ship
with, which is what keeps those references intact on your instance.

## 1. Super metrics

1. In the top bar click **Operate**, then in the left pane **Administration**, **Configurations**, and the **Super
   Metrics** tile.
2. Click the **⋯** beside **ADD**, then **Import**, and choose the folder's `supermetrics/*.import.json`.
3. Leave **Skip import** selected under **In case of a conflict** (it is the default) and click **IMPORT**. The
   dialog reports how many were imported and how many skipped because they were already there.

Each super metric keeps its id and arrives assigned to its object types: select one and its details show **Assigned
Object Types**. None is switched on yet: the same details show **Policies Enabled (0)**, which is step 4.

## 2. Views

**Operate**, **Dashboards**, then **Views** and **Manage** in the panel beside the menu. Click **⋯**, **Import**,
choose the folder's `views/*.import.zip`, keep **Skip import** (the default) and click **IMPORT**. The first time, the
dialog reads **Views imported successfully**. On a second import of the same file it reads **Views import failed**,
and **See more** explains that views with the same ids already exist: that is the skip, and nothing changed.

## 3. The dashboard

**Operate**, **Dashboards**, then **Manage** in the panel beside the menu. Click **⋯**, **Import**, and choose the
folder's `dashboard/*.import.zip` as it is. **In case of a conflict** defaults to **Rename**, which keeps a dashboard
of the same name that you already have and adds this one beside it; **Overwrite** replaces it in place. You own the
dashboard you import. Import it after the views: if you imported it first, import the views now, then import the
dashboard again with **Overwrite**.

## 4. Switch the super metrics on in a policy

An imported super metric collects nothing until it is enabled in the policy that governs the objects it reads, and
nothing reports the gap: its columns simply stay blank. The policy is the one applied to the hosts, clusters or VMs
you want covered; if you have created no policies of your own, it is the **Default Policy**.

- **One at a time.** On the **Super Metrics** screen, select the super metric and click **EDIT**. The editor has four
  steps; open **4 - Policies**, tick the policy under the object type the super metric should compute on, and click
  **UPDATE**. A folder's README says which object type that is when a super metric is assigned to more than one.
- **Several at once.** Under **Administration**, **Configurations**, open the **Policy Definition** tile, select the
  policy and click **Edit Policy**, then **Metrics and Properties**. Filter by object type, select the super metrics,
  choose **Activate**, and save the policy.

## 5. Wait, then read the dashboard

The editor's Policies step says it plainly: after one collection cycle the super metric begins collecting, and it
appears on each object of its type. Collection runs every five minutes by default, so give it two cycles before you
judge. A dashboard whose rows stay blank after that is almost always step 4.

## Two ways in, and why this page uses the list screens

VCF Operations offers a second route for super metrics and views: **Administration**, **Control Panel**, the **Content
Management** tile, its **Import** tab, with a folder's `*.contentpkg.zip`. It is built for moving content between
instances, which is what you are doing, and for super metrics and views it gives the same result: on 9.1.1 a package
imported there kept each id and assigned the object types, and its results table counts what was imported, skipped and
failed. This page uses the list screens for three reasons:

- **Their defaults are safe.** The Super Metrics and Views imports default to **Skip import**. Content Management
  defaults to **Overwrite existing content**, which on 9.1.1 replaced an existing super metric in place, including a
  value you had edited, such as a price. If you use it, choose **Skip item(s)**.
- **One pattern, beside the dashboard's.** Each is **⋯**, **Import** on the screen where that content lives.
- **The Views import is the stricter reader.** A view whose title carries an unescaped `&` is refused there, while a
  content import's parser lets it through, so a view that imports through Views is one the console reads.

Content Management is also a whole-environment backup and transfer tool that keeps each item's original owner. That
suits global content such as super metrics and views; a dashboard is owned by a user, so it always goes through
**Dashboards**, **Manage**, **Import**, which makes you its owner.

## If something looks wrong

- **The Views import says it failed.** Open **See more**: "views with the same ids already exist" is the skip, not a
  fault. Any other message is a real refusal; check the folder's README.
- **An import fails outright.** VMware's 9.1 page on importing super metrics notes that an import fails when the file
  refers to an object that does not exist on the target instance; check the folder's README for what the content
  expects to find.
- **Blank columns or tiles.** The super metrics are not switched on in the policy that governs those objects (step 4),
  or not enough collection cycles have passed (step 5).
- **You want a newer version of the files.** Import with **Overwrite** only when you want the shipped version to
  replace what is on your instance, including any value you edited; otherwise keep **Skip import** and make the change
  in the editor.

## Where these steps come from

Read in VMware's documentation for VCF 9.1: the Super Metrics tab, exporting and importing a super metric, and the
policy workspace's Metrics and Properties page on techdocs.broadcom.com, and Broadcom knowledge base article 445394 for
the Content Management path. Read on a VCF Operations 9.1.1 instance on 2026-10-09: every screen and default above;
both super metric routes, each with a throwaway super metric, keeping the shipped id, assigning the object type and
enabling no policy; what **Overwrite** and **Skip** did to a super metric that already existed; a throwaway view
imported through Views under its shipped id, its second import reported as an existing id, and its deletion; the
memory-tiering folder's own super metric and view files through the list screens; and its dashboard replaced in place
with **Overwrite**.
