output "api_url" {
  description = "Public API address; the website's config.js points here."
  value       = aws_apigatewayv2_stage.default.invoke_url
}

output "deploy_role_arn" {
  description = "Set as the AWS_DEPLOY_ROLE_ARN variable in the GitHub repo."
  value       = aws_iam_role.deploy.arn
}
