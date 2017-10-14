# cdk-shrinkwrap

Builds a tarball of charms, resources, snaps, and a deploy script for offline installs.

## Shrinkwrap

```sh
$ ./shrinkwrap.py canonical-kubernetes --channel stable

kubernetes-worker
    Downloading charm...
    Downloading resource cni-amd64.tgz...
    Downloading resource cni-s390x.tgz...
    Downloading resource kube-proxy.snap...
    Downloading resource kubectl.snap...
    Downloading resource kubelet.snap...
kubernetes-master
    Downloading charm...
    Downloading resource cdk-addons.snap...
    Downloading resource kube-apiserver.snap...
    Downloading resource kube-controller-manager.snap...
    Downloading resource kube-scheduler.snap...
    Downloading resource kubectl.snap...
etcd
    Downloading charm...
    Downloading resource etcd.snap...
    Downloading resource snapshot.gz...
flannel
    Downloading charm...
    Downloading resource flannel-amd64.gz...
    Downloading resource flannel-s390x.gz...
kubeapi-load-balancer
    Downloading charm...
easyrsa
    Downloading charm...
    Downloading resource easyrsa.tgz...
Done.
```

This will create a tarball, `canonical-kubernetes.tar.gz`.

## Deploy

First, set up a juju controller and model and `juju switch` to your model. Then:

```sh
$ tar -xf canonical-kubernetes.tar.gz

$ cd canonical-kubernetes

$ ./deploy.sh

+ juju deploy ./charms/flannel
Deploying charm "local:xenial/flannel-0".
+ juju deploy ./charms/easyrsa
Deploying charm "local:xenial/easyrsa-0".
+ juju deploy ./charms/kubeapi-load-balancer
Deploying charm "local:xenial/kubeapi-load-balancer-0".
+ juju deploy ./charms/kubernetes-worker
Deploying charm "local:xenial/kubernetes-worker-0".
+ juju deploy ./charms/kubernetes-master
Deploying charm "local:xenial/kubernetes-master-0".
+ juju deploy ./charms/etcd
Deploying charm "local:xenial/etcd-0".
+ juju attach flannel flannel-amd64=./resources/flannel/flannel-amd64.gz
+ juju attach flannel flannel-s390x=./resources/flannel/flannel-s390x.gz
+ juju attach easyrsa easyrsa=./resources/easyrsa/easyrsa.tgz
+ juju attach kubernetes-worker cni-amd64=./resources/kubernetes-worker/cni-amd64.tgz
+ juju attach kubernetes-worker cni-s390x=./resources/kubernetes-worker/cni-s390x.tgz
+ juju attach kubernetes-worker kube-proxy=./resources/kubernetes-worker/kube-proxy.snap
+ juju attach kubernetes-worker kubectl=./resources/kubernetes-worker/kubectl.snap
+ juju attach kubernetes-worker kubelet=./resources/kubernetes-worker/kubelet.snap
+ juju attach kubernetes-master cdk-addons=./resources/kubernetes-master/cdk-addons.snap
+ juju attach kubernetes-master kube-apiserver=./resources/kubernetes-master/kube-apiserver.snap
+ juju attach kubernetes-master kube-controller-manager=./resources/kubernetes-master/kube-controller-manager.snap
+ juju attach kubernetes-master kube-scheduler=./resources/kubernetes-master/kube-scheduler.snap
+ juju attach kubernetes-master kubectl=./resources/kubernetes-master/kubectl.snap
+ juju attach etcd etcd=./resources/etcd/etcd.snap
+ juju attach etcd snapshot=./resources/etcd/snapshot.gz
+ juju relate kubernetes-master:kube-api-endpoint kubeapi-load-balancer:apiserver
+ juju relate kubernetes-master:loadbalancer kubeapi-load-balancer:loadbalancer
+ juju relate kubernetes-master:kube-control kubernetes-worker:kube-control
+ juju relate kubernetes-master:certificates easyrsa:client
+ juju relate etcd:certificates easyrsa:client
+ juju relate kubernetes-master:etcd etcd:db
+ juju relate kubernetes-worker:certificates easyrsa:client
+ juju relate kubernetes-worker:kube-api-endpoint kubeapi-load-balancer:website
+ juju relate kubeapi-load-balancer:certificates easyrsa:client
+ juju relate flannel:etcd etcd:db
+ juju relate flannel:cni kubernetes-master:cni
+ juju relate flannel:cni kubernetes-worker:cni
```

## Limitations

cdk-shrinkwrap can't build cross-platform tarballs. If you want a tarball for s390x, you'll need to
build it on s390x.
