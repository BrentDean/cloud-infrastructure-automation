package main

import (
	"fmt"
	"strings"

	"github.com/aws/aws-cdk-go/awscdk/v2"
	"github.com/aws/aws-cdk-go/awscdk/v2/awscloudwatch"
	"github.com/aws/aws-cdk-go/awscdk/v2/awscloudwatchactions"
	"github.com/aws/aws-cdk-go/awscdk/v2/awskms"
	"github.com/aws/aws-cdk-go/awscdk/v2/awssns"
	"github.com/aws/constructs-go/constructs/v10"
	"github.com/aws/jsii-runtime-go"
)

var monitoredRoles = []string{"web", "app", "broker", "db"}

func parameterID(role string) string {
	return strings.ToUpper(role[:1]) + role[1:] + "InstanceId"
}

func NewOperationsMonitoringStack(
	scope constructs.Construct,
	id string,
	props *awscdk.StackProps,
) awscdk.Stack {
	stack := awscdk.NewStack(scope, jsii.String(id), props)

	managedSNSEncryptionKey := awskms.Alias_FromAliasName(
		stack,
		jsii.String("AwsManagedSnsKey"),
		jsii.String("alias/aws/sns"),
	)
	alertTopic := awssns.NewTopic(stack, jsii.String("OperationsAlerts"), &awssns.TopicProps{
		DisplayName: jsii.String("LabOps operations alerts"),
		MasterKey:   managedSNSEncryptionKey,
	})

	dashboard := awscloudwatch.NewDashboard(
		stack,
		jsii.String("OperationsDashboard"),
		&awscloudwatch.DashboardProps{
			DashboardName: jsii.String("labops-operations"),
		},
	)

	for _, role := range monitoredRoles {
		paramName := parameterID(role)
		instanceID := awscdk.NewCfnParameter(
			stack,
			jsii.String(paramName),
			&awscdk.CfnParameterProps{
				Type:           jsii.String("AWS::EC2::Instance::Id"),
				Description:    jsii.String(fmt.Sprintf("Terraform-created %s EC2 instance ID", role)),
				AllowedPattern: jsii.String("^i-[0-9a-f]+$"),
			},
		)

		statusMetric := awscloudwatch.NewMetric(&awscloudwatch.MetricProps{
			Namespace:  jsii.String("AWS/EC2"),
			MetricName: jsii.String("StatusCheckFailed"),
			DimensionsMap: &map[string]*string{
				"InstanceId": instanceID.ValueAsString(),
			},
			Period:    awscdk.Duration_Minutes(jsii.Number(1)),
			Statistic: jsii.String("Maximum"),
		})

		alarm := awscloudwatch.NewAlarm(
			stack,
			jsii.String(strings.ToUpper(role[:1])+role[1:]+"StatusCheckAlarm"),
			&awscloudwatch.AlarmProps{
				AlarmDescription:   jsii.String(fmt.Sprintf("EC2 status check failed for LabOps %s tier", role)),
				Metric:             statusMetric,
				Threshold:          jsii.Number(1),
				EvaluationPeriods:  jsii.Number(2),
				DatapointsToAlarm:  jsii.Number(2),
				ComparisonOperator: awscloudwatch.ComparisonOperator_GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
				TreatMissingData:   awscloudwatch.TreatMissingData_NOT_BREACHING,
			},
		)
		alarm.AddAlarmAction(awscloudwatchactions.NewSnsAction(alertTopic))

		dashboard.AddWidgets(
			awscloudwatch.NewAlarmWidget(&awscloudwatch.AlarmWidgetProps{
				Title: jsii.String(fmt.Sprintf("%s EC2 status", strings.ToUpper(role))),
				Alarm: alarm,
				Width: jsii.Number(6),
			}),
		)
	}

	awscdk.NewCfnOutput(stack, jsii.String("AlertTopicArn"), &awscdk.CfnOutputProps{
		Value:       alertTopic.TopicArn(),
		Description: jsii.String("SNS topic receiving CloudWatch alarm notifications"),
	})
	awscdk.NewCfnOutput(stack, jsii.String("DashboardName"), &awscdk.CfnOutputProps{
		Value:       dashboard.DashboardName(),
		Description: jsii.String("CloudWatch operations dashboard"),
	})

	return stack
}
