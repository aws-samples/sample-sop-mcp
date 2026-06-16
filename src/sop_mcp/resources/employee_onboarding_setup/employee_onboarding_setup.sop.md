---
name: employee_onboarding_setup
description: 'Onboarding a new employee: obtain details from HR, register an alias in IT, send an alias selection email, and send a hardware selection list.'
version: 1
owner: HR Department
stage: preprod
---

# Standard Operating Procedure: Employee Onboarding Setup

## Overview

Onboarding a new employee by obtaining their details from HR, registering an alias in IT, sending an alias selection email, and providing a hardware selection list.

## Parameters

- **employee_name** (optional): Full name of the new hire, if already known. Otherwise obtained from HR in Step 1.
- **hr_partner** (optional): Alias or email of the assigned HR partner. Defaults to the HR department on-call.

## Steps

### 1. Obtain New Employee Information from HR Partner

Retrieve the new employee's details from the HR department partner. Contact the assigned HR partner, request full name, personal email, planned start date, department, and job title, and confirm the information is accurate. If the HR partner is unavailable, escalate to the HR department manager.

**Constraints:**
- You MUST obtain the employee's full name, personal email, and start date before proceeding
- You MUST confirm the information accuracy with the HR partner
- You SHOULD obtain the department name and job title for hardware selection purposes
- You SHOULD document the HR partner's name for audit trail
- You MAY request additional information such as preferred name or accessibility needs

**Expected Output:** Full name, personal email, start date (YYYY-MM-DD), department, job title, and HR partner name.

**Time Estimate:** 15-30 minutes

### 2. Register an Alias at IT

Create a unique alias for the new employee in the IT system. Generate a proposed alias from the employee's name (first initial + last name), verify it's unique, and register it. If the alias is taken, generate alternatives and retry.

**Constraints:**
- You MUST verify the alias is unique before registering it
- You MUST register the alias before sending any communication to the employee
- You MUST follow the alias naming convention (first initial + last name)
- You SHOULD attempt at least 3 alias variations before flagging for manual review
- You MAY reserve the alias temporarily while awaiting employee confirmation

**Expected Output:** The registered alias, the format used, the registration status (REGISTERED / PENDING / CONFLICT), and — on conflict — the list of attempted aliases plus the registration timestamp (YYYY-MM-DD HH:MM).

**Time Estimate:** 10 minutes

### 3. Send Alias Selection Email to New Employee

Notify the new employee of their alias options and allow them to confirm or request a different one. Compose an email to the employee's personal email with the registered alias and at least one alternative, set a response deadline of 3 business days, and follow up if no response arrives.

**Constraints:**
- You MUST send the email to the employee's personal or temporary email address
- You MUST include the registered alias and instructions for requesting changes
- You MUST set a response deadline of 3 business days
- You SHOULD include at least one alternative alias option
- You SHOULD send a follow-up reminder if no response is received by the deadline
- You MAY include a welcome message and general onboarding information

**Expected Output:** The recipient email, the subject line, the alias options included, the response deadline (YYYY-MM-DD), and the sent status (SENT / FAILED) — with an error description if FAILED.

**Time Estimate:** 10 minutes

### 4. Send Hardware Selection List to New Employee

Provide the new employee with a list of available hardware to choose from. Retrieve the hardware catalog appropriate for the employee's role, compose an email with the selection list and out-of-stock notes, and set a 5-business-day selection deadline.

**Constraints:**
- You MUST send the hardware list appropriate for the employee's role and department
- You MUST include instructions on how to submit the hardware selection
- You MUST set a selection deadline of 5 business days
- You SHOULD include all available categories (laptop, monitor, peripherals)
- You SHOULD note any out-of-stock items with estimated availability
- You MAY include recommended configurations based on the employee's role

**Expected Output:** The recipient email, the subject line, the number of hardware options and categories offered, the selection deadline (YYYY-MM-DD), and the sent status (SENT / FAILED) — with an error description if FAILED.

**Time Estimate:** 10 minutes
