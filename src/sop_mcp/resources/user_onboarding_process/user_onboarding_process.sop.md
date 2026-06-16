---
name: user_onboarding_process
description: Standard process for onboarding new users to the organization's systems and tools with consistent access provisioning.
version: 1
owner: IT Operations Team
stage: preprod
---

# Standard Operating Procedure: User Onboarding Process

## Overview

Standard process for onboarding new users to the organization's systems and tools, ensuring consistent access provisioning and a smooth first-day experience.

## Parameters

- **user_name** (required): The full name of the new user being onboarded.
- **role** (required): The user's role, used to resolve the role-based access matrix.

## Steps

### 1. Create User Identity

Provision the new user's core identity in the organization's IAM system. Verify hire confirmation and start date from HR, create the account in the identity provider (Okta, Azure AD, etc.), set a temporary password, configure MFA enrollment, and assign the user to the appropriate organisational unit.

**Constraints:**
- You MUST verify HR confirmation before creating any accounts
- You MUST enforce MFA enrollment on first login
- You SHOULD use the naming convention: firstname.lastname
- You MAY create an alias if there is a naming conflict

**Expected Output:** The provisioned username, identity-provider user ID, temporary password delivery method, and MFA enrollment status.

**Time Estimate:** 15-20 minutes

### 2. Provision Application Access

Grant access to the tools and applications required for the user's role. Review the role-based access matrix, assign SSO application entitlements, create accounts in non-SSO systems, and verify access by confirming the user appears in each application's user list.

**Constraints:**
- You MUST follow the principle of least privilege
- You MUST only grant access listed in the role-based access matrix
- You SHOULD document any exceptions to standard access
- You MAY grant temporary elevated access with manager approval and an expiry date

**Expected Output:** The list of applications granted, the entitlement method (SSO vs local account) for each, and the verification status per application.

**Time Estimate:** 20-40 minutes

### 3. Send Welcome Package and Verify

Deliver credentials and onboarding materials to the new user and confirm everything works. Send a welcome email with login instructions and temporary credentials, include onboarding documentation and training material links, schedule a 15-minute IT check-in for day one, and verify the user can sign in and access every provisioned application.

**Constraints:**
- You MUST send credentials through a secure channel because plaintext email for passwords exposes them to downstream caches and mail-system logs
- You MUST verify access works before marking onboarding complete
- You SHOULD include a troubleshooting FAQ in the welcome package
- You MAY assign a buddy from the team for first-week support

**Expected Output:** Confirmation of the secure credential delivery channel used, the scheduled IT check-in time, and a sign-in verification result per provisioned application.

**Time Estimate:** 15 minutes
