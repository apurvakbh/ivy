# global
import ivy
import ivy.functional.frontends.torch as torch_frontend
from ivy.functional.frontends.torch.func_wrapper import to_ivy_arrays_and_back
from ivy.func_wrapper import with_unsupported_dtypes


def _get_reduction_func(reduction):
    if reduction == "none":
        ret = lambda x: x
    elif reduction == "mean":
        ret = ivy.mean
    elif reduction == "sum":
        ret = ivy.sum
    else:
        raise ivy.utils.exceptions.IvyException(
            "{} is not a valid value for reduction".format(reduction)
        )
    return ret


def _legacy_get_string(size_average, reduce):
    if size_average is None:
        size_average = True
    if reduce is None:
        reduce = True
    if size_average and reduce:
        ret = "mean"
    elif reduce:
        ret = "sum"
    else:
        ret = "none"
    return ret


def _get_reduction(reduction, size_average=None, reduce=None):
    if size_average is not None or reduce is not None:
        return _get_reduction_func(_legacy_get_string(size_average, reduce))
    else:
        return _get_reduction_func(reduction)


def _get_reduction_method(reduction, to_reduce):
    if reduction == "none":
        ret = to_reduce
    elif reduction == "mean":
        ret = ivy.mean(to_reduce)
    elif reduction == "sum":
        ret = ivy.sum(to_reduce)
    else:
        raise ivy.utils.exceptions.IvyException(
            f"{reduction} is not a valid value for reduction"
        )
    return ret


def _get_reduction_string(size_average, reduce):
    if size_average is None:
        size_average = True
    if reduce is None:
        reduce = True
    if size_average and reduce:
        ret = "mean"
    elif reduce:
        ret = "sum"
    else:
        ret = "none"
    return ret


def _apply_reduction(reduction, size_average, reduce, to_reduce):
    if size_average is not None or reduce is not None:
        reduction = _get_reduction_string(size_average, reduce)
        return _get_reduction_method(reduction, to_reduce)
    else:
        return _get_reduction_method(reduction, to_reduce)


@to_ivy_arrays_and_back
def cross_entropy(
    input,
    target,
    weight=None,
    size_average=None,
    ignore_index=-100,
    reduce=None,
    reduction="mean",
    label_smoothing=0.0,
):
    input = ivy.softmax(input)
    ret = ivy.cross_entropy(target, input, epsilon=label_smoothing)
    if weight is not None:
        ret = ivy.multiply(weight, ret)
    ret = _apply_reduction(reduction, size_average, reduce, ret)
    return ret


@to_ivy_arrays_and_back
@with_unsupported_dtypes({"1.11.0 and below": ("float16", "bfloat16")}, "torch")
def binary_cross_entropy(
    input, target, weight=None, size_average=None, reduce=None, reduction="mean"
):
    reduction = _get_reduction(reduction, size_average, reduce)
    result = ivy.binary_cross_entropy(target, input, epsilon=0.0)

    if weight is not None:
        result = ivy.multiply(weight, result)
    result = reduction(result)
    return result


@to_ivy_arrays_and_back
def binary_cross_entropy_with_logits(
    input,
    target,
    weight=None,
    size_average=None,
    reduce=None,
    reduction="mean",
    pos_weight=None,
):
    reduction = _get_reduction(reduction, size_average, reduce)
    result = ivy.binary_cross_entropy_with_logits(target, input, pos_weight=pos_weight)

    if weight is not None:
        result = ivy.multiply(weight, result)
    result = reduction(result).astype(target.dtype)
    return result


@to_ivy_arrays_and_back
@with_unsupported_dtypes({"1.11.0 and below": ("float16", "bfloat16")}, "torch")
def cosine_embedding_loss(
    input1, input2, target, margin=0.0, size_average=None, reduce=None, reduction="mean"
):
    def norm(input, axis):
        return ivy.sqrt(ivy.sum(ivy.square(input), axis=axis))

    def cosine_similarity(x1, x2):
        axis = None
        if len(x1.shape) == len(x2.shape) and len(x2.shape) == 2:
            axis = 1
        input1_norm = norm(x1, axis=axis)
        input2_norm = norm(x2, axis=axis)
        norm_mm = input1_norm * input2_norm
        norm_mm, eps = torch_frontend.promote_types_of_torch_inputs(norm_mm, 1e-08)
        return ivy.sum(x1 * x2, axis=axis) / ivy.maximum(norm_mm, eps)

    def calculate_loss(x1, x2, target):
        cos = cosine_similarity(x1, x2)
        if target == ivy.array(1.0):
            loss = 1.0 - cos
        elif target == ivy.array(-1.0):
            loss = ivy.maximum(ivy.array(0.0), cos - ivy.array(margin))
        else:
            _, zero = torch_frontend.promote_types_of_torch_inputs(
                input1, ivy.array(0.0)
            )
            return zero

        return loss

    ivy.utils.assertions.check_true(
        target.ndim + 1 == input1.ndim and target.ndim + 1 == input2.ndim,
        "{}D target tensor expects {}D input tensors, but "
        "found inputs with sizes {} and {}.".format(
            target.ndim, target.ndim + 1, list(input1.shape), list(input2.shape)
        ),
    )

    ivy.utils.assertions.check_true(
        target.ndim < 2, "0D or 1D target tensor expected, multi-target not supported"
    )

    ivy.utils.assertions.check_shape(input1, input2)

    if target.ndim == 1:
        ivy.utils.assertions.check_true(
            target.shape[0] == input1.shape[0],
            "The size of target tensor ({}) must match the size of input tensor ({}) "
            "at non-singleton dimension 0 ".format(target.shape[0], input1.shape[0]),
        )

    if target.ndim == 0:
        loss = calculate_loss(input1, input2, target)
    else:
        loss = ivy.array(
            [
                calculate_loss(input1[i], input2[i], target[i])
                for i in range(input1.shape[0])
            ]
        )

    reduction = _get_reduction(reduction, size_average, reduce)
    loss = reduction(loss)
    return loss


@to_ivy_arrays_and_back
def mse_loss(input, target, size_average=None, reduce=None, reduction="mean"):
    reduction = _get_reduction(reduction, size_average, reduce)
    result = ivy.square(input - target)
    result = reduction(result)
    return result


@to_ivy_arrays_and_back
@with_unsupported_dtypes({"1.11.0 and below": ("float16", "bfloat16")}, "torch")
def smooth_l1_loss(
    input,
    target,
    size_average=None,
    reduce=None,
    reduction="mean",
    beta=1.0,
):
    beta = ivy.array(beta, device=input.device)
    reduction = _get_reduction(reduction, size_average, reduce)

    if beta < 1e-5:
        # [Copied and modified from fvcore]
        # if beta == 0, then torch.where will result in nan gradients when
        # the chain rule is applied due to pytorch implementation details
        # (the False branch "0.5 * _diff_abs ** 2 / 0" has an incoming
        # gradient of zeros, rather than "no gradient"). To avoid this
        # issue, we define small values of beta to be exactly l1 loss.
        loss = ivy.abs(input - target)
    else:
        _diff_abs = ivy.abs(input - target)

        loss = ivy.where(
            _diff_abs < beta,
            0.5 * _diff_abs**2 / beta,
            _diff_abs - 0.5 * beta,
        )

    ret = reduction(loss)

    return ret


@to_ivy_arrays_and_back
def huber_loss(
    input,
    target,
    reduction="mean",
    delta=1.0,
):
    delta = ivy.array(delta)
    _diff_abs = ivy.abs(ivy.subtract(input, target))

    loss = ivy.where(
        _diff_abs < delta,  # If |xᵢ - yᵢ| < δ
        0.5 * _diff_abs**2,  # lᵢ = 0.5(xᵢ - yᵢ)²
        delta * (_diff_abs - 0.5 * delta),
    )  # lᵢ = δ(|xᵢ - yᵢ| - 0.5 * δ)

    reduction = _get_reduction(reduction)
    ret = reduction(loss)

    return ivy.astype(ret, input.dtype)


@to_ivy_arrays_and_back
def l1_loss(
    input,
    target,
    size_average=None,
    reduce=None,
    reduction="mean",
):
    loss = ivy.abs(input - target)
    reduction = _get_reduction(reduction, size_average, reduce)
    ret = reduction(loss)
    return ret


@to_ivy_arrays_and_back
def nll_loss(
    input,
    target,
    weight=None,
    size_average=None,
    ignore_index=-100,
    reduce=None,
    reduction="mean",
):
    out = ivy.zeros_like(target)

    if len(input.shape) == 1:
        for i in range(len(target)):
            out[i] = input[target[i]]
    else:
        for i in range(len(target)):
            out[i] = input[i][target[i]]
    loss = -out

    if weight is not None:
        loss = ivy.multiply(weight, loss)
    reduct = _get_reduction(reduction, size_average, reduce)
    ret = reduct(loss)

    return ret


@to_ivy_arrays_and_back
@with_unsupported_dtypes({"1.11.0 and below": ("float16", "bfloat16")}, "torch")
def soft_margin_loss(
    input,
    target,
    size_average=None,
    reduce=None,
    reduction="mean",
):
    loss = ivy.log1p(ivy.exp(-input * target))
    reduction = _get_reduction(reduction, size_average, reduce)
    ret = reduction(loss)
    return ret


@to_ivy_arrays_and_back
@with_unsupported_dtypes({"1.11.0 and below": ("float16", "bfloat16")}, "torch")
def kl_div(
    input, target, size_average=None, reduce=None, reduction="mean", log_target=False
):
    size = ivy.shape(input)

    if len(size) < 1:
        size = [1]

    def loss_fn():
        if log_target:
            return ivy.exp(target) * (target - input)
        return target * (ivy.log(target) - input)

    def batchmean(x):
        if not reduce:
            return x / size[0]

        if size_average:
            return ivy.mean(x) / size[0]

        return ivy.sum(x) / size[0]

    loss = ivy.nan_to_num(loss_fn())

    if reduction == "batchmean":
        reduction = batchmean
    else:
        reduction = _get_reduction(reduction, size_average, reduce)

    return reduction(loss)


@to_ivy_arrays_and_back
@with_unsupported_dtypes({"1.11.0 and below": ("float16", "bfloat16")}, "torch")
def margin_ranking_loss(
    input1,
    input2,
    target,
    margin=0.0,
    size_average=None,
    reduce=None,
    reduction="mean",
):
    loss = -1 * target * (input1 - input2) + margin
    loss = ivy.where(loss < 0, 0, loss)
    reduction = _get_reduction(reduction, size_average, reduce)
    return reduction(loss)


@to_ivy_arrays_and_back
@with_unsupported_dtypes({"1.11.0 and below": ("float16", "bfloat16")}, "torch")
def poisson_nll_loss(
    input,
    target,
    log_input=True,
    full=False,
    size_average=None,
    eps=1e-8,
    reduce=None,
    reduction="mean",
):
    if log_input:
        loss = ivy.exp(input) - target * input
    else:
        loss = input - target * ivy.log(input + eps)
    if full:
        approximation = (
            target * ivy.log(target) - target + 0.5 * ivy.log(2 * ivy.pi * target)
        )
        loss += ivy.where(target > 1, approximation, 0)

    reduction = _get_reduction(reduction, size_average, reduce)
    return reduction(loss)


@to_ivy_arrays_and_back
@with_unsupported_dtypes({"1.11.0 and below": ("float16", "bfloat16")}, "torch")
@to_ivy_arrays_and_back
def hinge_embedding_loss(
    input,
    target,
    margin=1.0,
    size_average=None,
    reduce=None,
    reduction="mean",
):
    margin = ivy.array(margin)

    loss = ivy.where(
        ivy.logical_or(target == -1, target == 1),
        ivy.where(target == 1, input, ivy.maximum(0, margin - input)),
        ivy.maximum(margin, input),
    )

    reduction = _get_reduction(reduction, size_average, reduce)
    ret = reduction(loss)

    return ivy.astype(ret, input.dtype)
