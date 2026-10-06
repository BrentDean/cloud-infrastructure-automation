package main

import (
	"github.com/aws/aws-cdk-go/awscdk/v2"
	"github.com/aws/jsii-runtime-go"
)

func main() {
	app := awscdk.NewApp(&awscdk.AppProps{
		Outdir: jsii.String("cdk.out"),
	})
	NewOperationsMonitoringStack(app, "LabOpsOperationsMonitoring", &awscdk.StackProps{
		Description: jsii.String(
			"Operational alarms and dashboard for the Terraform-managed LabOps EC2 tiers",
		),
	})
	app.Synth(nil)
}
