output "bucket_name" {
  value = aws_s3_bucket.state.id
}

output "region" {
  value = var.region
}
