# SecureTrack-Lite User Manual

SecureTrack-Lite is a web application for evaluating FortiGate firewall policies against access requests. It helps users and administrators review which policy is the best fit for a requested source, destination, and service.

## 1. What the application does

The application allows you to:

- log in with a username and password
- see the services you are allowed to use
- use the Policy Evaluation service to test access requests
- review ranked firewall policy results
- upload multiple requests in a CSV file for batch evaluation

## 2. Getting started

### Start the application

From the project directory, run:

```bash
source venv/bin/activate
python api/app.py
```

Then open:

```text
http://127.0.0.1:5000
```

### First login

If you are starting with a fresh local database, the application creates a default administrator account:

- Username: admin
- Password: admin

It is recommended to change the password after the first login.

## 3. User roles

### Administrator
An administrator can:

- manage users
- create and edit services
- assign services to users through subscriptions
- change their own password
- access the admin dashboard

### Regular user
A regular user can:

- log in to the client dashboard
- view the services they are subscribed to
- use the Policy Evaluation service if access is granted

## 4. How a regular user works with the app

### Step 1: Log in

1. Open the application in your browser.
2. Enter your username and password.
3. Click Sign In.

### Step 2: View your available services

After login, you will see your dashboard. It shows the services that are currently assigned to your account.

If you have access to the Policy Evaluation service, you will see an Open Service button for that card.

If you do not have access to any service, you will see a message saying that no services are available.

### Step 3: Open the Policy Evaluation service

1. On the dashboard, click Open Service for Policy Evaluation.
2. The Policy Evaluation page opens.
3. You can now enter an access request.

## 5. Using the Policy Evaluation service

### Single request evaluation

On the Policy Evaluation page, enter:

- Source Addresses
- Destination Addresses
- Services

You can select values from the available address and service lists.

After submitting the form, the app shows:

- the best matching policy
- a ranked list of matching policies
- source, destination, and service match counts
- interface information
- penalty information for broad rules

### Batch evaluation with CSV

You can also upload a CSV file with multiple requests.

Expected CSV format:

```csv
source,destination,port
192.168.10.25,10.10.10.15,tcp-443
192.168.20.10,10.20.20.20,tcp-80
```

The app evaluates each row and shows the top suggestions for each request.

## 6. What happens if a user has no access?

If a regular user is not subscribed to the Policy Evaluation service, they will:

- see the dashboard
- not see the Open Service button for Policy Evaluation
- be blocked from opening the service page

In that case, the user should contact an administrator.

## 7. Administrator tasks

Administrators can manage access through the admin portal.

### Manage users

An administrator can:

- create new users
- edit existing users
- delete users
- change user roles

### Manage services

An administrator can:

- create new services
- edit existing services
- delete services

### Assign service access

An administrator can assign services to users by managing subscriptions. This is how a regular user gets permission to use the Policy Evaluation service.

## 8. Troubleshooting

### Cannot log in

- verify your username and password
- if you are using the initial local setup, try the default admin account
- ask an administrator to confirm your account is active

### No services appear on the dashboard

- you may not be subscribed to any active service
- ask an administrator to assign you a service

### Policy Evaluation is unavailable

- make sure the required data files exist in the data folder
- if data files are missing, the collector may need to be run against a FortiGate device

## 9. Notes

The application depends on FortiGate policy data to evaluate requests. If the project has not collected data yet, the Policy Evaluation service may not be useful until the data files are populated.
