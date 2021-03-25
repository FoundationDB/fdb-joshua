.ONESHELL:
.PHONY: apply delete

apply:
	kubectl kustomize . > all.yaml
	kubectl apply -f all.yaml

delete:
	-kubectl delete -f all.yaml
	-rm all.yaml

