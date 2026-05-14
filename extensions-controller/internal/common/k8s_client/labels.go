package k8s_client

import (
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/labels"
	"sigs.k8s.io/controller-runtime/pkg/client"
)

func (k *K8sClient) HasLabel(obj client.Object, key string) bool {
	_, ok := obj.GetLabels()[key]
	return ok
}

func (k *K8sClient) GetLabel(obj client.Object, key string) (value string, found bool) {
	labels := obj.GetLabels()
	if labels == nil {
		return "", false
	}
	value, found = labels[key]
	return value, found
}

func (k *K8sClient) RemoveLabel(obj client.Object, key string) {
	labels := obj.GetLabels()

	if labels == nil {
		return
	}

	delete(labels, key)

	obj.SetLabels(labels)
}

func (k *K8sClient) SetLabel(obj client.Object, key, value string) {
	labels := obj.GetLabels()

	if labels == nil {
		labels = make(map[string]string, 1)
	}

	labels[key] = value

	obj.SetLabels(labels)
}

func (k *K8sClient) areLabelsMatchLabelSelector(labelsToCheck map[string]string, labelSelector metav1.LabelSelector) (bool, error) {
	selector, err := metav1.LabelSelectorAsSelector(&labelSelector)
	if err != nil {
		return false, err
	}
	return k.isSelectorMatchesLabels(selector, labelsToCheck), nil
}

func (k *K8sClient) isSelectorMatchesLabels(selector labels.Selector, labelsToCheck map[string]string) bool {
	set := labels.Set(labelsToCheck)
	return selector.Matches(set)
}

// AreLabelsMatchLabelSelector is a standalone function that checks if labels match a label selector.
// This is a utility function that doesn't require a K8sClient instance.
func AreLabelsMatchLabelSelector(labelsToCheck map[string]string, labelSelector metav1.LabelSelector) (bool, error) {
	selector, err := metav1.LabelSelectorAsSelector(&labelSelector)
	if err != nil {
		return false, err
	}
	set := labels.Set(labelsToCheck)
	return selector.Matches(set), nil
}
