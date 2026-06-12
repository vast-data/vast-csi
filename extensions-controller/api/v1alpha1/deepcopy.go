package v1alpha1

// DeepCopyInto copies all properties of this spec into another spec.
func (in *VastReplicationContentSpec) DeepCopyInto(out *VastReplicationContentSpec) {
	*out = *in
	if in.PVCs != nil {
		in, out := &in.PVCs, &out.PVCs
		*out = make(PVCList, len(*in))
		copy(*out, *in)
	}
	if in.ProtectionPolicyNames != nil {
		in, out := &in.ProtectionPolicyNames, &out.ProtectionPolicyNames
		*out = make([]string, len(*in))
		copy(*out, *in)
	}
}

// DeepCopy returns a deep copy of this VastReplicationContentSpec.
func (in *VastReplicationContentSpec) DeepCopy() *VastReplicationContentSpec {
	if in == nil {
		return nil
	}
	out := new(VastReplicationContentSpec)
	in.DeepCopyInto(out)
	return out
}

// DeepCopyInto copies all properties of this spec into another spec.
func (in *VastStorageClassReplicationSpec) DeepCopyInto(out *VastStorageClassReplicationSpec) {
	*out = *in
	if in.ProtectionTopology != nil {
		in, out := &in.ProtectionTopology, &out.ProtectionTopology
		*out = make([]ReplicationTarget, len(*in))
		copy(*out, *in)
	}
	if in.ProtectionPolicyTemplate.Params != nil {
		params := make([]ProtectionPolicyFrame, len(in.ProtectionPolicyTemplate.Params))
		copy(params, in.ProtectionPolicyTemplate.Params)
		out.ProtectionPolicyTemplate.Params = params
	}
}

// DeepCopy returns a deep copy of this VastStorageClassReplicationSpec.
func (in *VastStorageClassReplicationSpec) DeepCopy() *VastStorageClassReplicationSpec {
	if in == nil {
		return nil
	}
	out := new(VastStorageClassReplicationSpec)
	in.DeepCopyInto(out)
	return out
}

// DeepCopyInto copies all properties of this spec into another spec.
func (in *VastVolumeReplicationSpec) DeepCopyInto(out *VastVolumeReplicationSpec) {
	*out = *in
	if in.ProtectionTopology != nil {
		in, out := &in.ProtectionTopology, &out.ProtectionTopology
		*out = make([]ReplicationTarget, len(*in))
		copy(*out, *in)
	}
	if in.ProtectionPolicyTemplate.Params != nil {
		params := make([]ProtectionPolicyFrame, len(in.ProtectionPolicyTemplate.Params))
		copy(params, in.ProtectionPolicyTemplate.Params)
		out.ProtectionPolicyTemplate.Params = params
	}
}

// DeepCopy returns a deep copy of this VastVolumeReplicationSpec.
func (in *VastVolumeReplicationSpec) DeepCopy() *VastVolumeReplicationSpec {
	if in == nil {
		return nil
	}
	out := new(VastVolumeReplicationSpec)
	in.DeepCopyInto(out)
	return out
}

// DeepCopyInto copies all properties of this status into another status.
func (in *VastStorageClassReplicationStatus) DeepCopyInto(out *VastStorageClassReplicationStatus) {
	*out = *in
}

// DeepCopy returns a deep copy of this VastStorageClassReplicationStatus.
func (in *VastStorageClassReplicationStatus) DeepCopy() *VastStorageClassReplicationStatus {
	if in == nil {
		return nil
	}
	out := new(VastStorageClassReplicationStatus)
	in.DeepCopyInto(out)
	return out
}

// DeepCopyInto copies all properties of this status into another status.
func (in *VastVolumeReplicationStatus) DeepCopyInto(out *VastVolumeReplicationStatus) {
	*out = *in
}

// DeepCopy returns a deep copy of this VastVolumeReplicationStatus.
func (in *VastVolumeReplicationStatus) DeepCopy() *VastVolumeReplicationStatus {
	if in == nil {
		return nil
	}
	out := new(VastVolumeReplicationStatus)
	in.DeepCopyInto(out)
	return out
}

// DeepCopyInto copies all properties of this status into another status.
func (in *VastReplicationContentStatus) DeepCopyInto(out *VastReplicationContentStatus) {
	*out = *in
	if in.PVCs != nil {
		in, out := &in.PVCs, &out.PVCs
		*out = make(PVCList, len(*in))
		copy(*out, *in)
	}
}

// DeepCopy returns a deep copy of this VastReplicationContentStatus.
func (in *VastReplicationContentStatus) DeepCopy() *VastReplicationContentStatus {
	if in == nil {
		return nil
	}
	out := new(VastReplicationContentStatus)
	in.DeepCopyInto(out)
	return out
}
