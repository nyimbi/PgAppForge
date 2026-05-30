# Workflow Definition Language (WDL) - Inspired by JHipster JDL
# Employee Onboarding Workflow Example

workflow EmployeeOnboarding {
  version: "1.2.0"
  description: "Complete employee onboarding process with approvals"

  # Entity references (existing or generated)
  entities {
    Employee: existing
    Document: generated {
      fields: [
        documentType: {type: string, required: true},
        fileName: {type: string, required: true},
        filePath: {type: string, required: true},
        uploadedAt: {type: datetime, default: now},
        verifiedBy: {type: string, nullable: true}
      ]
    }
    Equipment: existing
  }

  # Step definitions with rich metadata
  steps {
    PersonalInfo {
      title: "Personal Information"
      description: "Collect basic employee details and emergency contacts"
      icon: "user"
      estimatedTime: "15 minutes"

      fields: [
        firstName: {
          type: string,
          required: true,
          validation: {minLength: 2, maxLength: 50},
          placeholder: "Enter first name"
        },
        lastName: {
          type: string,
          required: true,
          validation: {minLength: 2, maxLength: 50},
          placeholder: "Enter last name"
        },
        email: {
          type: email,
          required: true,
          unique: true,
          validation: {pattern: "^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$"},
          placeholder: "employee@company.com"
        },
        phone: {
          type: string,
          validation: {pattern: "^[0-9-+()\\s]+$"},
          placeholder: "+1 (555) 123-4567"
        },
        address: {
          type: textarea,
          validation: {maxLength: 500},
          rows: 3,
          placeholder: "Street address, City, State, ZIP"
        },
        emergencyContactName: {
          type: string,
          required: true,
          placeholder: "Emergency contact full name"
        },
        emergencyContactPhone: {
          type: string,
          required: true,
          validation: {pattern: "^[0-9-+()\\s]+$"},
          placeholder: "Emergency contact phone"
        },
        startDate: {
          type: date,
          required: true,
          validation: {min: "today", max: "+90 days"},
          default: "+14 days"
        }
      ]

      layout: {
        sections: [
          {
            title: "Basic Information",
            fields: ["firstName", "lastName", "email", "phone"]
          },
          {
            title: "Address & Contact",
            fields: ["address", "emergencyContactName", "emergencyContactPhone"]
          },
          {
            title: "Employment Details",
            fields: ["startDate"]
          }
        ]
      }

      navigation: {
        next: DocumentUpload,
        canSkip: false,
        saveAsDraft: true,
        autoSave: true,
        autoSaveInterval: "30s"
      }

      permissions: {
        view: [hr, employee, manager],
        edit: [hr, employee],
        admin: [hr_admin]
      }

      validation: {
        custom: "validateEmployeeUniqueness",
        business: ["checkEmailDomain", "validateStartDate"]
      }
    }

    DocumentUpload {
      title: "Document Upload"
      description: "Upload required employment documents"
      icon: "upload"
      estimatedTime: "10 minutes"

      fields: [
        idDocument: {
          type: file,
          required: true,
          accept: ["image/*", "application/pdf"],
          maxSize: "5MB",
          label: "Government ID (Driver's License, Passport, etc.)",
          helpText: "Upload a clear photo or scan of your government-issued ID"
        },
        socialSecurityCard: {
          type: file,
          accept: ["image/*", "application/pdf"],
          maxSize: "5MB",
          label: "Social Security Card",
          helpText: "Required for US employees"
        },
        passport: {
          type: file,
          accept: ["image/*", "application/pdf"],
          maxSize: "5MB",
          label: "Passport (if applicable)",
          helpText: "Required for international employees"
        },
        i9Form: {
          type: file,
          required: true,
          accept: ["application/pdf"],
          maxSize: "10MB",
          label: "Completed I-9 Form",
          helpText: "Download, complete, and upload the I-9 employment eligibility form"
        },
        bankingInfo: {
          type: file,
          accept: ["image/*", "application/pdf"],
          maxSize: "5MB",
          label: "Banking Information",
          helpText: "Voided check or bank statement for direct deposit setup"
        }
      ]

      fileProcessing: {
        autoExtractText: true,
        autoValidateFormat: true,
        generateThumbnails: true,
        virusScan: true
      }

      validation: {
        custom: "validateDocumentQuality",
        business: ["checkDocumentExpiry", "validateI9Completion"],
        security: ["scanForPII", "validateFileIntegrity"]
      }

      navigation: {
        previous: PersonalInfo,
        next: ManagerApproval,
        conditional: {
          field: "requiresBackgroundCheck",
          value: true,
          next: BackgroundVerification
        }
      }

      permissions: {
        view: [hr, employee, manager],
        edit: [hr, employee],
        approve: [hr_admin],
        download: [hr, hr_admin]
      }

      compliance: {
        retention: "7 years",
        encryption: "AES-256",
        accessLog: true,
        gdprCompliant: true
      }
    }

    ManagerApproval {
      title: "Manager Review & Approval"
      description: "Direct manager reviews hire and sets initial employment terms"
      icon: "check-circle"
      estimatedTime: "20 minutes"

      fields: [
        approvalStatus: {
          type: select,
          options: [
            {value: "approved", label: "Approved", color: "green"},
            {value: "rejected", label: "Rejected", color: "red"},
            {value: "needs_revision", label: "Needs Revision", color: "orange"}
          ],
          required: true,
          label: "Approval Decision"
        },
        comments: {
          type: textarea,
          required_if: "approvalStatus in ['rejected', 'needs_revision']",
          validation: {minLength: 10, maxLength: 1000},
          placeholder: "Please provide detailed feedback...",
          rows: 4
        },
        department: {
          type: select,
          source: "departments",
          required_if: "approvalStatus == 'approved'",
          label: "Department Assignment"
        },
        position: {
          type: select,
          source: "positions",
          required_if: "approvalStatus == 'approved'",
          filter_by: "department",
          label: "Position/Role"
        },
        reportingManager: {
          type: select,
          source: "managers",
          required_if: "approvalStatus == 'approved'",
          filter_by: "department",
          label: "Direct Reporting Manager"
        },
        salaryGrade: {
          type: select,
          source: "salaryGrades",
          required_if: "approvalStatus == 'approved'",
          filter_by: "position",
          label: "Salary Grade"
        },
        workLocation: {
          type: select,
          options: ["remote", "office", "hybrid"],
          required_if: "approvalStatus == 'approved'",
          label: "Work Location Type"
        },
        officeLocation: {
          type: select,
          source: "offices",
          required_if: "workLocation in ['office', 'hybrid']",
          label: "Primary Office Location"
        }
      ]

      automation: {
        onApproval: [
          "sendWelcomeEmail",
          "createEmployeeRecord",
          "assignEmployeeId",
          "generateOfferLetter",
          "scheduleBadgeCreation"
        ],
        onRejection: [
          "notifyHR",
          "archiveApplication",
          "sendRejectionNotification"
        ],
        onRevision: [
          "notifyEmployee",
          "flagForRevision"
        ]
      }

      navigation: {
        previous: DocumentUpload,
        next: ITSetup,
        conditional: [
          {
            field: "approvalStatus",
            value: "rejected",
            next: "END"
          },
          {
            field: "approvalStatus",
            value: "needs_revision",
            next: PersonalInfo
          }
        ]
      }

      permissions: {
        view: [manager, hr, hr_admin],
        edit: [manager, hr_admin],
        readonly: [hr],
        delegate: [manager, hr_admin]
      }

      escalation: {
        timeout: "48h",
        escalateTo: "hr_admin",
        notification: ["email", "slack"]
      }

      audit: {
        logLevel: "detailed",
        requireDigitalSignature: true,
        immutableRecord: true
      }
    }

    ITSetup {
      title: "IT Equipment & Access Provisioning"
      description: "Configure IT equipment, accounts, and system access"
      icon: "laptop"
      estimatedTime: "45 minutes"

      fields: [
        laptopModel: {
          type: select,
          source: "availableLaptops",
          required: true,
          label: "Laptop Assignment",
          displayField: "model_description"
        },
        monitorCount: {
          type: select,
          options: [1, 2],
          default: 1,
          label: "Number of Monitors"
        },
        phoneAssignment: {
          type: select,
          source: "availablePhones",
          label: "Company Phone",
          nullable: true
        },
        accessRequests: {
          type: multiselect,
          source: "systemAccess",
          required: true,
          label: "System Access Requests",
          groupBy: "category",
          helpText: "Select all systems the employee needs access to"
        },
        workspaceLocation: {
          type: select,
          source: "workspaces",
          required_if: "workLocation in ['office', 'hybrid']",
          filter_by: "officeLocation",
          label: "Workspace Assignment"
        },
        parkingSpot: {
          type: select,
          source: "availableParkingSpots",
          filter_by: "officeLocation",
          label: "Parking Spot (if needed)",
          nullable: true
        },
        softwareLicenses: {
          type: multiselect,
          source: "softwareLicenses",
          filter_by: "department",
          label: "Required Software Licenses"
        }
      ]

      automation: {
        beforeStep: [
          "checkEquipmentAvailability",
          "validateAccessPermissions",
          "reserveEquipment"
        ],
        afterStep: [
          "provisionAccounts",
          "scheduleEquipmentDelivery",
          "createServiceTickets",
          "generateAccessCards",
          "setupVPNAccess"
        ]
      }

      integrations: {
        serviceNow: {
          action: "createTicket",
          template: "new_employee_setup",
          priority: "normal"
        },
        activeDirectory: {
          action: "createUser",
          groupMembership: "auto_assign_by_department"
        },
        assetManagement: {
          action: "assignEquipment",
          trackingEnabled: true
        },
        slack: {
          action: "createAccount",
          autoInviteChannels: ["#general", "#announcements"]
        }
      }

      navigation: {
        previous: ManagerApproval,
        next: "END"
      }

      permissions: {
        view: [it_admin, hr, manager],
        edit: [it_admin],
        readonly: [hr, manager],
        approve: [it_manager]
      }

      sla: {
        completionTime: "24h",
        businessHoursOnly: true
      }
    }
  }

  # Workflow triggers and events
  triggers {
    start: {
      event: "employee_hired",
      condition: "employee.status == 'hired' AND employee.onboarding_required == true",
      initialStep: "PersonalInfo",
      priority: "normal"
    }

    escalation: {
      event: "step_timeout",
      condition: "step.duration > step.sla.timeout",
      action: "notifyManager",
      escalationLevels: [
        {after: "24h", notify: ["direct_manager"]},
        {after: "48h", notify: ["hr_admin", "department_head"]},
        {after: "72h", notify: ["hr_director", "ceo"]}
      ]
    }

    completion: {
      event: "all_steps_complete",
      action: [
        "updateEmployeeStatus",
        "sendCompletionNotification",
        "scheduleOrientationMeeting",
        "addToPayrollSystem",
        "generateWelcomePackage"
      ]
    }

    exception: {
      event: "workflow_error",
      action: ["logError", "notifyAdmin", "createSupportTicket"]
    }
  }

  # Service Level Agreements
  sla {
    totalDuration: "5 business days",
    stepTimeouts: {
      PersonalInfo: "24h",
      DocumentUpload: "48h",
      ManagerApproval: "24h",
      ITSetup: "48h"
    },
    businessHours: {
      start: "09:00",
      end: "17:00",
      timezone: "America/New_York",
      excludeWeekends: true,
      excludeHolidays: true
    }
  }

  # Notification configuration
  notifications {
    email: {
      templates: "employee_onboarding_v2",
      triggers: [
        "step_start",
        "step_complete",
        "approval_needed",
        "escalation",
        "completion",
        "error"
      ],
      customization: {
        branding: true,
        personalization: true,
        attachDocuments: true
      }
    }

    slack: {
      channels: ["#hr-notifications", "#it-requests", "#manager-alerts"],
      triggers: ["approval_needed", "escalation", "completion", "error"],
      mentionUsers: true,
      useThreads: true
    }

    sms: {
      triggers: ["urgent_escalation", "critical_error"],
      recipients: ["hr_admin", "it_manager"]
    }

    inApp: {
      triggers: ["step_start", "step_complete", "approval_needed"],
      realTime: true,
      persistent: true
    }
  }

  # Analytics and reporting
  analytics {
    track: [
      "step_completion_time",
      "total_workflow_duration",
      "user_abandonment_rate",
      "error_frequency",
      "approval_turnaround_time",
      "equipment_provisioning_time"
    ],

    reports: [
      {
        name: "Onboarding Efficiency",
        schedule: "weekly",
        recipients: ["hr_admin", "operations_manager"]
      },
      {
        name: "Bottleneck Analysis",
        schedule: "monthly",
        recipients: ["hr_director", "it_director"]
      }
    ],

    dashboards: {
      realTime: true,
      filters: ["department", "location", "date_range"],
      visualizations: ["timeline", "funnel", "heatmap"]
    }
  }

  # Compliance and audit
  compliance {
    retention: {
      completed_workflows: "7 years",
      abandoned_workflows: "2 years",
      audit_logs: "10 years"
    },

    privacy: {
      dataClassification: "confidential",
      encryptionRequired: true,
      accessLogging: true,
      rightToErasure: true
    },

    regulations: ["GDPR", "CCPA", "SOX", "HIPAA"],

    audit: {
      automaticBackup: true,
      immutableLogs: true,
      digitalSignatures: true,
      periodicReview: "quarterly"
    }
  }
}