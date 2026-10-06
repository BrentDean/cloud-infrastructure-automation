package main

import (
	"fmt"

	"github.com/aws/aws-cdk-go/awscdk/v2"
	"github.com/aws/aws-cdk-go/awscdk/v2/awscloudwatch"
	"github.com/aws/aws-cdk-go/awscdk/v2/awscloudwatchactions"
	"github.com/aws/aws-cdk-go/awscdk/v2/awssns"
	"github.com/aws/constructs-go/constructs/v10"
	"github.com/aws/jsii-runtime-go"
)

type OperationsStackProps struct {
	awscdk.StackProps
}

type instanceTarget struct {
	Name        string
	ParameterID string
}

func NewOperationsStack(
	scope constructs.Construct,
	id string,
	props *OperationsStackProps,
) awscdk.Stack {
	var stackProps awscdk.StackProps
	if props != nil {
		stackProps = props.StackProps
	}
	if stackProps.Description == nil {
		stackProps.Description = jsii.String(
			"Optional LabOps operational alarms/dashboard layered on Terraform-owned EC2.",
		)
	}

	stack := awscdk.NewStack(scope, jsii.String(id), &stackProps)

	alarmTopic := awssns.NewTopic(stack, jsii.String("OperationsAlarmTopic"), &awssns.TopicProps{
		DisplayName:      jsii.String("LabOps infrastructure alarms"),
		SignatureVersion: jsii.String("2"),
	})

	targets := []instanceTarget{
		{Name: "Web", ParameterID: "WebInstanceId"},
		{Name: "App", ParameterID: "AppInstanceId"},
		{Name: "Broker", ParameterID: "BrokerInstanceId"},
		{Name: "Database", ParameterID: "DatabaseInstanceId"},
	}

	cpuMetrics := make([]awscloudwatch.IMetric, 0, len(targets))

	for _, target := range targets {
		instanceID := awscdk.NewCfnParameter(
			stack,
			jsii.String(target.ParameterID),
			&awscdk.CfnParameterProps{
				Type:        jsii.String("AWS::EC2::Instance::Id"),
				Description: jsii.String(fmt.Sprintf("%s EC2 instance ID from Terraform output/run evidence.", target.Name)),
			},
		)

		statusMetric := ec2Metric(
			"StatusCheckFailed",
			instanceID.ValueAsString(),
			"Maximum",
			awscdk.Duration_Minutes(jsii.Number(1)),
		)
		statusAlarm := awscloudwatch.NewAlarm(
			stack,
			jsii.String(target.Name+"StatusCheckFailed"),
			&awscloudwatch.AlarmProps{
				Metric:             statusMetric,
				Threshold:          jsii.Number(1),
				EvaluationPeriods:  jsii.Number(2),
				DatapointsToAlarm:  jsii.Number(1),
				AlarmDescription:   jsii.String(fmt.Sprintf("%s EC2 instance reported a failed status check.", target.Name)),
				ComparisonOperator: awscloudwatch.ComparisonOperator_GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
			},
		)
		statusAlarm.AddAlarmAction(awscloudwatchactions.NewSnsAction(alarmTopic))

		cpuMetric := ec2Metric(
			"CPUUtilization",
			instanceID.ValueAsString(),
			"Average",
			awscdk.Duration_Minutes(jsii.Number(5)),
		)
		cpuMetrics = append(cpuMetrics, cpuMetric)

		if target.Name == "Broker" {
			brokerCPU := awscloudwatch.NewAlarm(
				stack,
				jsii.String("BrokerHighCPU"),
				&awscloudwatch.AlarmProps{
					Metric:             cpuMetric,
					Threshold:          jsii.Number(85),
					EvaluationPeriods:  jsii.Number(3),
					DatapointsToAlarm:  jsii.Number(2),
					AlarmDescription:   jsii.String("Broker EC2 CPU utilization is high for two of three periods."),
					ComparisonOperator: awscloudwatch.ComparisonOperator_GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
				},
			)
			brokerCPU.AddAlarmAction(awscloudwatchactions.NewSnsAction(alarmTopic))
		}
	}

	dashboard := awscloudwatch.NewDashboard(
		stack,
		jsii.String("OperationsDashboard"),
		&awscloudwatch.DashboardProps{
			DashboardName: jsii.String("labops-operations"),
		},
	)
	dashboard.AddWidgets(
		awscloudwatch.NewGraphWidget(&awscloudwatch.GraphWidgetProps{
			Title:  jsii.String("EC2 CPU utilization"),
			Left:   &cpuMetrics,
			Width:  jsii.Number(24),
			Height: jsii.Number(6),
		}),
	)

	awscdk.NewCfnOutput(stack, jsii.String("AlarmTopicArn"), &awscdk.CfnOutputProps{
		Value:       alarmTopic.TopicArn(),
		Description: jsii.String("SNS topic ARN used by all LabOps operations alarms."),
	})
	awscdk.NewCfnOutput(stack, jsii.String("OperationsDashboardName"), &awscdk.CfnOutputProps{
		Value:       dashboard.DashboardName(),
		Description: jsii.String("CloudWatch dashboard created by the optional CDK operations layer."),
	})

	return stack
}

func ec2Metric(
	metricName string,
	instanceID *string,
	statistic string,
	period awscdk.Duration,
) awscloudwatch.Metric {
	dimensions := map[string]*string{
		"InstanceId": instanceID,
	}
	return awscloudwatch.NewMetric(&awscloudwatch.MetricProps{
		Namespace:     jsii.String("AWS/EC2"),
		MetricName:    jsii.String(metricName),
		DimensionsMap: &dimensions,
		Statistic:     jsii.String(statistic),
		Period:        period,
	})
}
