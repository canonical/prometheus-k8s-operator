Feature: Alert rule customizations
  As a Prometheus k8s operator
  I want to customize the alert rules provided by related charms via the
  alert_rule_customizations config option
  So that I can remove or patch rules the way my deployment requires

  Background:
    Given the charm provides the following alert rules:
      """
      main-group:
        - alert: AlphaFiring
          expr: 'up{job="alpha"} == 0'
          for: 5m
          labels:
            severity: critical
            juju_application: app-alpha
          annotations:
            summary: Alpha is down
        - alert: BetaFiring
          expr: 'up{job="beta"} == 0'
          for: 2m
          labels:
            severity: warning
            juju_application: app-beta
          annotations:
            summary: Beta is degraded
      secondary-group:
        - alert: GammaFiring
          expr: rate(errors_total[5m]) > 0
          for: 1m
          labels:
            severity: warning
          annotations:
            summary: Gamma has errors
      """

  Scenario: The charm becomes blocked when the customization is invalid YAML
    When the customization is set to:
      """
      remove: [unclosed bracket
      """
    Then the charm is in BlockedStatus for alert_rule_customizations
    And all provided alert rules are still written unchanged

  Scenario: The charm becomes blocked when the customization has invalid keys
    When the customization is set to:
      """
      removee:
        - where:
            alert: AlphaFiring
      """
    Then the charm is in BlockedStatus for alert_rule_customizations
    And all provided alert rules are still written unchanged

  Scenario: The charm becomes blocked when the customization has an invalid operation key
    When the customization is set to:
      """
      remove:
        - wheree:
            alert: AlphaFiring
      """
    Then the charm is in BlockedStatus for alert_rule_customizations
    And all provided alert rules are still written unchanged

  Scenario: Removing an alert by name drops only that alert
    When the customization is set to:
      """
      remove:
        - where:
            alert: AlphaFiring
      """
    Then alert "AlphaFiring" is not written
    And alert "BetaFiring" is written
    And alert "GammaFiring" is written

  Scenario: Removing an alert by group name drops the entire group
    When the customization is set to:
      """
      remove:
        - where:
            group: secondary-group
      """
    Then alert "GammaFiring" is not written
    And alert "AlphaFiring" is written
    And alert "BetaFiring" is written

  Scenario: Patching sets a field on a matching alert
    When the customization is set to:
      """
      patch:
        - where:
            alert: AlphaFiring
          set:
            for: 30m
      """
    Then alert "AlphaFiring" has "for" equal to "30m"
    And alert "BetaFiring" has "for" equal to "2m"

  Scenario: Patching replaces the expression of a matching alert
    When the customization is set to:
      """
      patch:
        - where:
            alert: AlphaFiring
          set:
            expr: 'up{job="alpha", env="prod"} == 0'
      """
    Then alert "AlphaFiring" has "expr" equal to 'up{job="alpha", env="prod"} == 0'

  Scenario: Patching adds a new label and preserves existing labels
    When the customization is set to:
      """
      patch:
        - where:
            alert: AlphaFiring
          set:
            labels:
              team: platform
      """
    Then alert "AlphaFiring" has label "team" equal to "platform"
    And alert "AlphaFiring" has label "severity" equal to "critical"

  Scenario: Patching overwrites an existing label
    When the customization is set to:
      """
      patch:
        - where:
            alert: AlphaFiring
          set:
            labels:
              severity: info
      """
    Then alert "AlphaFiring" has label "severity" equal to "info"

  Scenario: Patching matches by label value and only touches matching alerts
    When the customization is set to:
      """
      patch:
        - where:
            labels:
              severity: warning
          set:
            for: 10m
      """
    Then alert "BetaFiring" has "for" equal to "10m"
    And alert "AlphaFiring" has "for" equal to "5m"

  Scenario: Multiple patch operations are each applied
    When the customization is set to:
      """
      patch:
        - where:
            alert: AlphaFiring
          set:
            for: 15m
        - where:
            alert: BetaFiring
          set:
            for: 20m
      """
    Then alert "AlphaFiring" has "for" equal to "15m"
    And alert "BetaFiring" has "for" equal to "20m"

  Scenario: Removing and patching can be combined
    When the customization is set to:
      """
      remove:
        - where:
            alert: AlphaFiring
      patch:
        - where:
            alert: BetaFiring
          set:
            for: 25m
      """
    Then alert "AlphaFiring" is not written
    And alert "BetaFiring" has "for" equal to "25m"

  Scenario: Patching and removing apply to rules from both relation endpoints
    Given the charm also provides the following remote write alert rules:
      """
      rw-group:
        - alert: AlphaFiring
          expr: 'up{job="rw"} == 0'
          for: 2m
          labels:
            severity: critical
      """
    When the customization is set to:
      """
      remove:
        - where:
            alert: AlphaFiring
      """
    Then alert "AlphaFiring" is not written in group "rw-group"
    And alert "GammaFiring" is written

  Scenario: The charm becomes blocked when the customization yields invalid rules
    When the customization is set to:
      """
      patch:
        - where:
            alert: AlphaFiring
          set:
            expr: "this is not valid {{{promql"
      """
    Then the charm is in BlockedStatus for alert_rule_customizations

  Scenario: A remove that matches nothing results in no change
    When the customization is set to:
      """
      remove:
        - where:
            alert: TotallyMadeUpAlert
      """
    Then the written alert rules are unchanged
    And the charm is in ActiveStatus for alert_rule_customizations

  Scenario: A patch that matches nothing results in no change
    When the customization is set to:
      """
      patch:
        - where:
            alert: TotallyMadeUpAlert
          set:
            for: 30m
      """
    Then the written alert rules are unchanged
    And the charm is in ActiveStatus for alert_rule_customizations

  Scenario: A remove and patch that match nothing result in no change
    When the customization is set to:
      """
      remove:
        - where:
            alert: TotallyMadeUpAlert
      patch:
        - where:
            alert: AlsoDoesNotExist
          set:
            for: 30m
      """
    Then the written alert rules are unchanged
    And the charm is in ActiveStatus for alert_rule_customizations