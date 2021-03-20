from functools import partial
from pathlib import Path

import os
import configargparse
import torch
import importlib

from hivemind.proto.runtime_pb2 import CompressionType
from hivemind.server import Server
from hivemind.utils.threading import increase_file_limit
from hivemind.utils.logging import get_logger

logger = get_logger(__name__)

def add_custom_models_from_file(path):
    spec = importlib.util.spec_from_file_location(
        "custm_module", os.path.abspath(path))
    foo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(foo)

def main():
    # fmt:off
    parser = configargparse.ArgParser(default_config_files=["config.yml"])
    parser.add('-c', '--config', required=False, is_config_file=True, help='config file path')
    parser.add_argument('--listen_on', type=str, default='0.0.0.0:*', required=False,
                        help="'localhost' for local connections only, '0.0.0.0' for ipv4 '[::]' for ipv6")
    parser.add_argument('--num_experts', type=int, default=None, required=False, help="The number of experts to serve")
    parser.add_argument('--expert_pattern', type=str, default=None, required=False,
                        help='all expert uids will follow this pattern, e.g. "myexpert.[0:256].[0:1024]" will sample random expert uids'
                             ' between myexpert.0.0 and myexpert.255.1023 . Use either num_experts and this or expert_uids')
    parser.add_argument('--expert_uids', type=str, nargs="*", default=None, required=False,
                        help="specify the exact list of expert uids to create. Use either this or num_experts"
                             " and expert_pattern, not both")
    parser.add_argument('--expert_cls', type=str, default='ffn', required=False,
                        help="expert type from test_utils.layers, e.g. 'ffn', 'transformer', 'det_dropout' or 'nop'.")
    parser.add_argument('--hidden_dim', type=int, default=1024, required=False, help='main dimension for expert_cls')
    parser.add_argument('--num_handlers', type=int, default=None, required=False,
                        help='server will use this many processes to handle incoming requests')
    parser.add_argument('--max_batch_size', type=int, default=16384, required=False,
                        help='The total number of examples in the same batch will not exceed this value')
    parser.add_argument('--device', type=str, default=None, required=False,
                        help='all experts will use this device in torch notation; default: cuda if available else cpu')
    parser.add_argument('--optimizer', type=str, default='adam', required=False, help='adam, sgd or none')
    parser.add_argument('--no_dht', action='store_true', help='if specified, the server will not be attached to a dht')
    parser.add_argument('--initial_peers', type=str, nargs='*', required=False, default=[],
                        help='one or more peers that can welcome you to the dht, e.g. 1.2.3.4:1337 192.132.231.4:4321')
    parser.add_argument('--dht_port', type=int, default=None, required=False, help='DHT node will listen on this port')
    parser.add_argument('--increase_file_limit', action='store_true',
                        help='On *nix, this will increase the max number of processes '
                             'a server can spawn before hitting "Too many open files"; Use at your own risk.')
    parser.add_argument('--compression', type=str, default='NONE', required=False, help='Tensor compression '
                        'parameter for grpc. Can be NONE, MEANSTD or FLOAT16')
    parser.add_argument('--checkpoint_dir', type=Path, required=False, help='Directory to store expert checkpoints')
    parser.add_argument('--load_experts', action='store_true', help='Load experts from the checkpoint directory')

    parser.add_argument('--custom_module_path', type=str, default=None, required=False,
                        help='Path of a file with cutom nn.modules, wrapped into special decorator')

    # fmt:on
    args = vars(parser.parse_args())
    args.pop('config', None)
    optimizer = args.pop('optimizer')
    if optimizer == 'adam':
        optim_cls = torch.optim.Adam
    elif optimizer == 'sgd':
        optim_cls = partial(torch.optim.SGD, lr=0.01)
    elif optimizer == 'none':
        optim_cls = None
    else:
        raise ValueError("optim_cls must be adam, sgd or none")

    if args.pop('increase_file_limit'):
        increase_file_limit()

    compression_type = args.pop("compression")
    if compression_type == "MEANSTD":
        compression = CompressionType.MEANSTD_LAST_AXIS_FLOAT16
    else:
        compression = getattr(CompressionType, compression_type)

    custom_module_path = args.pop('custom_module_path')
    if custom_module_path is not None:
        add_custom_models_from_file(custom_module_path)

    server = Server.create(**args, optim_cls=optim_cls, start=True, compression=compression)

    try:
        server.join()
    except KeyboardInterrupt:
        logger.info("Caught KeyboardInterrupt, shutting down")
    finally:
        server.shutdown()


if __name__ == '__main__':
    main()
