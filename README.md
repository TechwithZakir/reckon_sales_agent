# Reckon Sales Agent

AI-assisted lead discovery, research, qualification and sales follow-up for
Frappe CRM, sold as a Reckon SaaS module.

**Current milestone: M0, Company ownership for Frappe CRM (unreleased).**
Discovery, research, scoring and campaigns are not implemented yet.

## Why M0 comes first

Reckon SaaS tenants are Companies on one shared site (`Tenant User Assignment`
in `reckon_saas_platform`). Frappe CRM's own records carry no Company, so without
this app every tenant on the site would see every other tenant's CRM data.

## How CRM is separated by Company

Every upstream CRM DocType falls into one of four groups (`crm_tenancy.py`):

| Group | DocTypes | Rule |
| --- | --- | --- |
| Data | CRM Lead, Deal, Organization, Task, Call Log, Notification, Product, Sales Hierarchy, Telephony Agent, Invitation, FCRM Note; Frappe Contact, Address, Communication, Comment, ToDo, File | Strictly per Company. Records with no Company are hidden from every tenant. |
| Master lists | CRM Territory, Industry, Lead Source, Lost Reason, Holiday List, Service Level Agreement, Dashboard, View Settings | Each Company keeps its own entries. Entries with no Company, such as CRM's seeded defaults, are shared and read-only for tenants. |
| Site configuration | FCRM Settings, CRM Global Settings, Fields Layout, Form Script, Lead/Deal/Communication Status, Twilio, Exotel and ERPNext CRM Settings | One copy per site. Tenants can read it; only vendor administrators can change it. |
| Child tables | CRM Contacts, Products, Status Change Log and the rest | Follow their parent record. |

How the rules are enforced:

- **Company field.** Scoped DocTypes get a read-only **Company** field
  (`rsa_company`). The creator's Company is set on every new record, and
  tenant users cannot choose or change it.
- **Inheritance.** Records created by system users, background jobs or Guest
  webhooks (telephony, web forms) inherit the Company of the record they are
  attached or linked to. A Comment, File or email on an ERPNext document follows
  that document's `company`. Records linked only after insert, such as emails
  and attachments, inherit on their next save.
- **Permission hooks.** List, report, link-search and document permission hooks
  limit tenant users to their own Company. A user with no active Company
  assignment sees nothing. CRM's and Frappe's own permission hooks still apply,
  and all of them must allow access.
- **Link checks.** Every Link and Dynamic Link, child tables included, must
  point to a record of the same Company, a shared master entry, or a record that
  isn't Company-owned. These checks are generic over DocType metadata, so new
  fields are covered automatically.
- **Lead conversion.** Conversion only reuses an organization, or a contact
  matched by email, from the lead's own Company. Upstream CRM matches both
  across the whole site. A contact created during a conversion run by a system
  user is adopted by the Deal's Company. Tenant users cannot claim unowned
  contacts.
- **Naming.** Records named after a field (organizations, products, master
  lists) get `<name> - <Company abbr>` when another Company already uses that
  name. Without this, a duplicate error would reveal the other tenant's record.
- **Backfill.** Install and migrate fill in the Company of existing data from
  linked records, or from the owner's single active Company. Communication,
  Comment, ToDo and File are filled in bulk with SQL. Existing master entries
  stay shared. Data that stays ambiguous remains hidden and is counted in the
  Error Log as "CRM Company Backfill Incomplete".

Scoping is active only when `reckon_saas_platform` is installed. Without it,
CRM behaves exactly as upstream.

## Install

```bash
bench get-app /absolute/path/to/reckon_sales_agent
bench --site <site> install-app reckon_sales_agent
bench --site <site> migrate
```

Install upstream Frappe CRM ([frappe/crm](https://github.com/frappe/crm)) first,
plus `reckon_saas_platform` on SaaS sites. No fork or other CRM extension app is
required.

The first migrate adds a column to the Communication, Comment, ToDo and File
tables, so it can take a while on large sites.

## Tests

The unit tests stub Frappe and need no bench:

```bash
python -m unittest discover -s tests
```

## Known limitations

- **Shared Frappe core DocTypes.** Contact, Address, Communication, Comment,
  ToDo and File are also used by ERPNext and Distribution, so on SaaS sites the
  same separation applies there too. System records with nothing to inherit
  from (for example each User's own contact, or system comments) stay hidden
  from tenants.
- **Statuses are site-wide.** Lead and Deal statuses are site configuration, so
  every Company uses the same pipeline stages.
- **SLAs and telephony.** CRM may apply a site-wide default SLA to any Company's
  records. Telephony (Twilio/Exotel) is configured per site, so incoming calls
  are matched to leads and deals across all tenants.
- **Deal-side contact lookup.** Upstream's `crm_deal.contact_exists` (used when
  a Deal is created directly) still matches contacts site-wide. It cannot link
  to another tenant's contact, because Deal validation refuses it, but the
  error confirms that the contact exists.
- **CRM invitations.** Invited users have no Company until they get a Tenant
  User Assignment, so they see nothing.
- **Endpoints that skip permissions.** Some upstream CRM endpoints read with
  `frappe.get_all`, which skips permission hooks (for example dashboard counts
  and group-by options). They need an audit on a real site.
- **Email-to-lead.** It creates unowned leads until an Email Account to Company
  mapping exists.
- **CRM Lead override.** `TenantCRMLead` assumes no other installed app
  overrides the CRM Lead class.
- **Database.** Bulk backfill SQL uses MariaDB `update ... join` syntax.
- **Not yet verified on a bench site.**
