.ONESHELL:
.PHONY: build apply delete clean

build:
	eval $$(minikube docker-env)
	mkdir -p tmp
	cp ../../joshua/joshua_model.py ./tmp/
	docker build -t agent-scaler:latest .
	rm tmp/joshua_model.py && rmdir tmp

apply:
	kubectl kustomize . > all.yaml
	kubectl apply -f all.yaml

delete:
	-kubectl delete -f all.yaml
	-rm all.yaml

clean:
	eval $$(minikube docker-env)
	docker rmi agent-scaler:latest

