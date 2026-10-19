# Reckon Sales Agent

AI-assisted lead discovery, research, qualification and sales follow-up for
Frappe CRM, sold as a Reckon SaaS module.

**Current milestone: M0, Company ownership for Frappe CRM (unreleased).**
Discovery, research, scoring and campaigns are not implemented yet.

## Why M0 comes first

Reckon SaaS tenants are Companies on one shared site (`Tenant User Assignment`
in `reckon_saas_platform`). Frappe CRM's own records carry no Company, so without
this app every tenant on the site would see every other tenant's leads and deals.

## What M0 adds

- A read-only **Company** field (`rsa_company`) on CRM Lead, CRM Deal,
  CRM Organization and CRM Task.
- The creator's Company is stamped on every new record. Tenant users cannot
  pick or change it. Records created by system jobs inherit the Company from
  their parent (a Task's reference, a Deal's lead or organization), or stay
  unowned and hidden from all tenants.
- List, report, link-search and document permission hooks limit tenant users
  to their own Company. A user with no active Company assignment sees nothing.
  CRM's own org-hierarchy hooks still apply, and both must allow access.
- Links must stay inside one Company: a Deal's organization and lead, and a
  Task's referenced Lead or Deal.
- Lead conversion only reuses an organization from the lead's own Company.
  Upstream CRM matches organization names across the whole site.
- A second tenant's organization with an existing name is saved as
  `<name> - <Company abbr>` instead of failing with a duplicate error that
  reveals the other tenant's customer.
- On install and migrate, existing records are backfilled from their parent
  record, or from the owner's single active Company. Anything ambiguous stays
  hidden and is reported in the Error Log as "CRM Company Backfill Incomplete".

Scoping is active only when `reckon_saas_platform` is installed. Without it,
CRM behaves exactly as upstream.

## Install

```bash
bench get-app /absolute/path/to/reckon_sales_agent
bench --site <site> install-app reckon_sales_agent
bench --site <site> migrate
```

Install `crm` (and `reckon_saas_platform` on SaaS sites) first.

## Tests

The unit tests stub Frappe and need no bench:

```bash
python -m unittest discover -s tests
```

## Known limitations

- Contact, CRM Note, CRM Call Log, Communication and `reckon_crm`'s Field Visit
  and Customer Location records are not Company-scoped yet.
- Some upstream CRM endpoints read with `frappe.get_all`, which skips
  permission hooks (for example dashboard counts and group-by options). They
  need an audit on a real site.
- Email-to-lead creates unowned leads until an Email Account to Company mapping
  exists.
- The controller overrides (`TenantCRMLead`, `TenantCRMOrganization`) assume
  that no other installed app overrides those CRM classes.
- Not yet verified on a bench site.
