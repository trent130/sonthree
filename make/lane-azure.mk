# Owned by lane azure. Edit only from the azure worktree.
.PHONY: accept-azure
accept-azure:
	az bicep build --file infra/main.bicep --stdout > /dev/null
