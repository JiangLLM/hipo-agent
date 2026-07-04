"""Mind2Web DOM rendering + metrics.

Vendored (with light trimming) from Agent Workflow Memory (AWM),
https://github.com/zorazrw/agent-workflow-memory  (Apache-2.0), which in turn
follows the MindAct observation format from OSU-NLP-Group/Mind2Web. We reuse this
ONLY as evaluation scaffolding (candidate pruning, observation rendering, the
standard metrics); our memory system is separate.
"""
from __future__ import annotations

import copy
import re
import string

from lxml import etree


def parse_act_str(act_str):
    pattern = re.compile(r"(?:^|\s)(CLICK|SELECT|TYPE)?\s?\[(.+?)\](?:\s\[(.+?)\])?")
    match = pattern.search(act_str or "")
    if match:
        return match.group(1), match.group(2), match.group(3)
    return None, None, None


def construct_act_str(op, val):
    if op is None:
        return " " if val is None else " " + val
    if op == "CLICK" or val is None:
        return op + " "
    return f"{op} {val}"


def get_target_act(example, target_element_id):
    op = example["operation"]["op"]
    value = example["operation"]["value"]
    target = f"{op} [{target_element_id}]"
    if op != "CLICK":
        target += f" [{value}]"
    return target


def calculate_f1(pred, label):
    pred = set(pred.strip().split())
    label = set(label.strip().split())
    pred = set(x for x in pred if x not in string.punctuation)
    label = set(x for x in label if x not in string.punctuation)
    if len(pred) == 0 and len(label) == 0:
        return 1
    if len(pred) == 0 or len(label) == 0:
        return 0
    tp = len(pred & label)
    fp = len(pred - label)
    fn = len(label - pred)
    if tp == 0:
        return 0
    precision = tp / (tp + fp)
    recall = tp / (tp + fn)
    if precision == 0 or recall == 0:
        return 0
    return 2 * precision * recall / (precision + recall)


def get_descendants(node, max_depth, current_depth=0):
    if current_depth > max_depth:
        return []
    out = []
    for child in node:
        out.append(child)
        out.extend(get_descendants(child, max_depth, current_depth + 1))
    return out


def get_attribute_repr(node, max_value_length=5, max_length=20):
    attr_values_set = set()
    attr_values = ""
    for attr in ["role", "aria_role", "type", "alt", "aria_description", "aria_label",
                 "label", "title", "name", "text_value", "value", "placeholder",
                 "input_checked", "input_value", "option_selected", "class"]:
        if attr in node.attrib and node.attrib[attr] is not None:
            value = node.attrib[attr].lower()
            if value in ["hidden", "none", "presentation", "null", "undefined"] or value.startswith("http"):
                continue
            value = value.split()
            value = " ".join([v for v in value if len(v) < 15][:max_value_length])
            if value and value not in attr_values_set:
                attr_values_set.add(value)
                attr_values += value + " "
    uid = node.attrib.get("backend_node_id", "")
    node.attrib.clear()
    if uid:
        node.attrib["id"] = uid
    if attr_values:
        node.attrib["meta"] = " ".join(attr_values.split()[:max_length])


def prune_tree(dom_tree, candidate_set, max_depth=5, max_children=50, max_sibling=3):
    nodes_to_keep = set()
    for candidate_id in candidate_set:
        found = dom_tree.xpath(f'//*[@backend_node_id="{candidate_id}"]')
        if not found:
            continue
        candidate_node = found[0]
        nodes_to_keep.add(candidate_node.attrib["backend_node_id"])
        nodes_to_keep.update(x.attrib.get("backend_node_id", "") for x in candidate_node.xpath("ancestor::*"))
        nodes_to_keep.update([x.attrib.get("backend_node_id", "")
                              for x in get_descendants(candidate_node, max_depth)][:max_children])
        parent = candidate_node.getparent()
        if parent is not None:
            siblings = [x for x in parent.getchildren() if x.tag != "text"]
            idx = siblings.index(candidate_node)
            nodes_to_keep.update(x.attrib.get("backend_node_id", "")
                                 for x in siblings[max(0, idx - max_sibling): idx + max_sibling + 1])
    new_tree = copy.deepcopy(dom_tree)
    for node in new_tree.xpath("//*")[::-1]:
        if node.tag != "text":
            is_keep = node.attrib.get("backend_node_id", "") in nodes_to_keep
            is_candidate = node.attrib.get("backend_node_id", "") in candidate_set
        else:
            is_keep = node.getparent().attrib.get("backend_node_id", "") in nodes_to_keep
            is_candidate = node.getparent().attrib.get("backend_node_id", "") in candidate_set
        if not is_keep and node.getparent() is not None:
            node.getparent().remove(node)
        else:
            if not is_candidate or node.tag == "text":
                node.attrib.pop("backend_node_id", None)
            if (len(node.attrib) == 0
                    and not any(x.tag == "text" for x in node.getchildren())
                    and node.getparent() is not None
                    and node.tag != "text"
                    and len(node.getchildren()) <= 1):
                for child in node.getchildren():
                    node.addprevious(child)
                node.getparent().remove(node)
    return new_tree


def get_tree_repr(tree, max_value_length=5, max_length=20, id_mapping=None, keep_html_brackets=False):
    if id_mapping is None:
        id_mapping = {}
    if isinstance(tree, str):
        tree = etree.fromstring(tree)
    else:
        tree = copy.deepcopy(tree)
    for node in tree.xpath("//*"):
        if node.tag != "text":
            if "backend_node_id" in node.attrib:
                if node.attrib["backend_node_id"] not in id_mapping:
                    id_mapping[node.attrib["backend_node_id"]] = len(id_mapping)
            get_attribute_repr(node, max_value_length, max_length)
        else:
            node.text = " ".join(node.text.split()[:max_length])
    tree_repr = etree.tostring(tree, encoding="unicode")
    tree_repr = tree_repr.replace('"', " ")
    tree_repr = tree_repr.replace("meta= ", "").replace("id= ", "id=").replace(" >", ">")
    tree_repr = re.sub(r"<text>(.*?)</text>", r"\1", tree_repr)
    if not keep_html_brackets:
        tree_repr = tree_repr.replace("/>", "$/$>")
        tree_repr = re.sub(r"</(.+?)>", r")", tree_repr)
        tree_repr = re.sub(r"<(.+?)>", r"(\1", tree_repr)
        tree_repr = tree_repr.replace("$/$", ")")
    for k, v in [("&quot;", '"'), ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
                 ("&nbsp;", " "), ("&ndash;", "-"), ("&rsquo;", "'"), ("&lsquo;", "'"),
                 ("&ldquo;", '"'), ("&rdquo;", '"'), ("&#39;", "'"), ("&#40;", "("), ("&#41;", ")")]:
        tree_repr = tree_repr.replace(k, v)
    tree_repr = re.sub(r"\s+", " ", tree_repr).strip()
    return tree_repr, id_mapping


def get_target_obs(dom_tree, target_element_ids):
    pruned = prune_tree(dom_tree, target_element_ids)
    repr_, _ = get_tree_repr(pruned, id_mapping={}, keep_html_brackets=True)
    return repr_


def get_top_k_obs(s: dict, top_k: int) -> tuple[str, list]:
    """Observation = pruned DOM of (gold pos + top-(k-1) ranked negatives)."""
    pos_ids = [c["backend_node_id"] for c in s["pos_candidates"]][:1]
    neg = sorted(s["neg_candidates"], key=lambda c: c["rank"])[: top_k - 1]
    neg_ids = [c["backend_node_id"] for c in neg]
    all_candidates = pos_ids + neg_ids
    obs = get_target_obs(etree.fromstring(s["cleaned_html"]), all_candidates)
    return obs, all_candidates
