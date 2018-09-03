#!/usr/bin/python3.6
# Copyright (C) 2018 Mo Zhou <lumin@debian.org>
# MIT/Expat License.

'''
Shogun needs the bazel dumps from bazelQuery.sh .

For extra compiler definitions .e.g TENSORFLOW_USE_JEMALLOC please lookup
  tensorflow/core/platform/default/build_config.bzl
'''

from typing import *
import sys
import re
import os
import argparse
from ninja_syntax import Writer


def filteroutExternal(sourcelist: List[str]) -> List[str]:
    '''
    Filter out external dependencies from bazel dependency dump
    '''
    external = set()
    ret = []
    for src in sourcelist:
        x = re.match('^@(\w*).*', src)
        if x is None:
            ret.append(src)
        else:
            external.update(x.groups())
    print('The specified source list requires external deps:', external)
    return ret


def mangleBazel(sourcelist: List[str]) -> List[str]:
    '''
    mangling source file path
    '''
    ret = []
    for x in sourcelist:
        x = re.sub('^//', '', x)
        x = re.sub(':', '/', x)
        ret.append(x)
    return ret


def eGrep(pat: str, sourcelist: List[str]) -> (List[str], List[str]):
    '''
    Just like grep -E
    '''
    match, unmatch = [], []
    for item in sourcelist:
        if re.match(pat, item):
            match.append(item)
        else:
            unmatch.append(item)
    return match, unmatch


def ninjaCommonHeader(cursor: Writer, ag: Any) -> None:
    '''
    Writes a common header to the ninja file. ag is parsed arguments.
    '''
    cursor.comment(f'automatically generated by {__file__}')
    cursor.variable('CXXFLAGS', '-std=c++14 -O2 -fPIC')
    cursor.variable('CXXFLAGS_terse', '-w')
    cursor.variable('INCLUDES', '-I. -I./debian/embedded/eigen/ -I./third_party/eigen3/'
            + ' -I/usr/include/gemmlowp')
    cursor.variable('LIBS', '-lpthread -lprotobuf')
    cursor.variable('PROTO_TEXT_ELF', f'{ag.B}/proto_text')
    cursor.rule('PROTOC', f'protoc $in --cpp_out {ag.B}')
    cursor.rule('PROTO_TEXT', f'$PROTO_TEXT_ELF {ag.B}/tensorflow/core tensorflow/core tensorflow/tools/proto_text/placeholder.txt $in')
    cursor.rule('GEN_VERSION_INFO', f'bash {ag.B}/tensorflow/tools/git/gen_git_source.sh $out')
    cursor.rule('CXX_OBJ', f'g++ $CXXFLAGS $CXXFLAGS_terse $INCLUDES -c $in -o $out')
    cursor.rule('CXX_EXEC', f'g++ $CXXFLAGS $CXXFLAGS_terse $INCLUDES $LIBS $in -o $out')
    cursor.rule('CXX_SHLIB', f'g++ -shared -fPIC $CXXFLAGS $CXXFLAGS_terse $INCLUDES $LIBS $in -o $out')
    cursor.rule('STATIC', f'ar rcs $out $in')


def ninjaProto(cur, protolist: List[str]) -> List[str]:
    '''
    write ninja rules for the protofiles. cur is ninja writer
    '''
    cclist = []
    for proto in protolist:
        output = [re.sub('.proto$', '.pb.cc', proto),
                re.sub('.proto$', '.pb.h', proto)]
        cur.build(output, 'PROTOC', inputs=proto)
        cclist.append(re.sub('.proto$', '.pb.cc', proto))
    return cclist


def ninjaProtoText(cur, protolist: List[str]) -> List[str]:
    '''
    write ninja rules for to proto_text files. cur is ninja writer
    '''
    cclist = []
    for proto in protolist:
        output = [re.sub('.proto$', '.pb_text.cc', proto),
                re.sub('.proto$', '.pb_text.h', proto),
                re.sub('.proto$', '.pb_text-impl.h', proto)]
        cur.build(output, 'PROTO_TEXT', inputs=proto)
        cclist.append(re.sub('.proto$', '.pb_text.cc', proto))
    return cclist


def ninjaCXXOBJ(cur, cclist: List[str]) -> List[str]:
    '''
    write ninja rules for building .cc files into object files
    '''
    objs = []
    for cc in cclist:
        output = re.sub('.cc$', '.o', cc)
        objs.append(cur.build(output, 'CXX_OBJ', inputs=cc)[0])
    return objs


def ninjaGenVersionInfo(cur, target):
    '''
    generate version_info.cc
    '''
    return res


def shogunProtoText(argv):
    '''
    Build proto_text
    '''
    ag = argparse.ArgumentParser()
    ag.add_argument('-i', help='list of source files', type=str, required=True)
    ag.add_argument('-o', help='where to write the ninja file', type=str, default='proto_text.ninja')
    ag.add_argument('-B', help='build directory', type=str, default='.')
    ag = ag.parse_args(argv)

    sourcelist = [l.strip() for l in open(ag.i, 'r').readlines()]
    sourcelist = filteroutExternal(sourcelist)
    sourcelist = mangleBazel(sourcelist)

    # Instantiate ninja writer
    cursor = Writer(open(ag.o, 'w'))
    ninjaCommonHeader(cursor, ag)

    # generate .pb.cc and .pb.h
    protolist, sourcelist = eGrep('.*.proto$', sourcelist)
    ninjaProto(cursor, protolist)

    # ignore .h files and third_party, and windows source
    _, sourcelist = eGrep('.*.h$', sourcelist)
    _, sourcelist = eGrep('^third_party', sourcelist)
    _, sourcelist = eGrep('.*windows/env_time.cc$', sourcelist)

    # compile .cc source
    cclist, sourcelist = eGrep('.*.cc', sourcelist)
    proto_text_objs = ninjaCXXOBJ(cursor, cclist)

    # link the final executable
    cursor.build('proto_text', 'CXX_EXEC', inputs=proto_text_objs)

    # fflush
    cursor.close()

    print('Unprocessed files:', sourcelist)


def shogunTFCoreProto(argv):
    '''
    Build tf_core_proto.a
    '''
    ag = argparse.ArgumentParser()
    ag.add_argument('-g', help='list of generated files', type=str, required=True)
    ag.add_argument('-o', help='where to write the ninja file', type=str, default='tf_core_proto.ninja')
    ag.add_argument('-B', help='build directory', type=str, default='.')
    ag = ag.parse_args(argv)

    genlist = filteroutExternal([l.strip() for l in open(ag.g, 'r').readlines()])
    genlist = mangleBazel(genlist)

    # Instantiate ninja writer
    cursor = Writer(open(ag.o, 'w'))
    ninjaCommonHeader(cursor, ag)

    # generate .pb.cc and .pb.h
    protolist, genlist = eGrep('.*.pb.h', genlist)
    protolist = [re.sub('.pb.h$', '.proto', x) for x in protolist]
    ninjaProto(cursor, protolist)
    _, genlist = eGrep('.*.pb.h', genlist)
    pbcclist, genlist = eGrep('.*.pb.cc', genlist)

    # generate .pb_text.cc .pb_text.h .pb_test-impl.h
    protolist, genlist = eGrep('.*.pb_text.h', genlist)
    pbtextcclist, genlist = eGrep('.*.pb_text.cc', genlist)
    _, genlist = eGrep('.*.pb_text-impl.h', genlist)
    protolist = [re.sub('.pb_text.h$', '.proto', x) for x in protolist]
    ninjaProtoText(cursor, protolist)
    pbcclist.extend(pbtextcclist)

    # compile .cc source
    tf_core_pb_obj = ninjaCXXOBJ(cursor, pbcclist)

    # link the final executable
    cursor.build('tf_core_proto.a', 'STATIC', inputs=tf_core_pb_obj)

    ## fflush
    cursor.close()


def shogunTFFrame(argv):
    '''
    Build libtensorflow_framework.so
    '''
    ag = argparse.ArgumentParser()
    ag.add_argument('-i', help='list of source files', type=str, required=True)
    ag.add_argument('-g', help='list of generated files', type=str, required=True)
    ag.add_argument('-o', help='where to write the ninja file', type=str, default='libtensorflow_framework.ninja')
    ag.add_argument('-B', help='build directory', type=str, default='.')
    ag = ag.parse_args(argv)

    srclist = filteroutExternal([l.strip() for l in open(ag.i, 'r').readlines()])
    genlist = filteroutExternal([l.strip() for l in open(ag.g, 'r').readlines()])
    srclist, genlist = mangleBazel(srclist), mangleBazel(genlist)

    # Instantiate ninja writer
    cursor = Writer(open(ag.o, 'w'))
    ninjaCommonHeader(cursor, ag)

    # generate .pb.cc and .pb.h
    _, srclist = eGrep('.*.proto$', srclist)
    protolist, genlist = eGrep('.*.pb.cc', genlist)
    _, genlist = eGrep('.*.pb.h', genlist)
    protolist = [re.sub('.pb.cc', '.proto', x) for x in protolist]
    ninjaProto(cursor, protolist)

    # generate .pb_text.cc .pb_text.h .pb_test-impl.h
    _, srclist = eGrep('.*.proto$', srclist)
    protolist, genlist = eGrep('.*.pb_text.cc', genlist)
    _, genlist = eGrep('.*.pb_text.h', genlist)
    _, genlist = eGrep('.*.pb_text-impl.h', genlist)
    protolist = [re.sub('.pb_text.cc$', '.proto', x) for x in protolist]
    ninjaProtoText(cursor, protolist)

    # generate version info, the last bit in list of generated files
    print('Unprocessed generated files:', genlist)
    assert(len(genlist) == 1)
    srclist.extend(cursor.build(genlist[0], 'GEN_VERSION_INFO'))

    # ignore .h files and third_party, and windows source
    _, srclist = eGrep('.*.h$', srclist)
    _, srclist = eGrep('^third_party', srclist)
    _, srclist = eGrep('.*windows/env_time.cc$', srclist)
    _, srclist = eGrep('.*platform/windows.*', srclist)
    _, srclist = eGrep('.*stream_executor.*', srclist) # due to CPU-only

    # compile .cc source
    cclist, srclist = eGrep('.*.cc', srclist)
    tf_framework_objs = ninjaCXXOBJ(cursor, cclist)

    # link the final executable
    cursor.build('libtensorflow_framework.so', 'CXX_SHLIB', inputs=tf_framework_objs)

    ## fflush
    cursor.close()
    print('Unprocessed source files:', srclist)


def shogunTFLibAndroid(argv):
    '''
    Build libtensorflow_android.so
    '''
    ag = argparse.ArgumentParser()
    ag.add_argument('-i', help='list of source files', type=str, required=True)
    ag.add_argument('-g', help='list of generated files', type=str, required=True)
    ag.add_argument('-o', help='where to write the ninja file', type=str, default='libtensorflow_android.ninja')
    ag.add_argument('-B', help='build directory', type=str, default='.')
    ag = ag.parse_args(argv)

    srclist = filteroutExternal([l.strip() for l in open(ag.i, 'r').readlines()])
    genlist = filteroutExternal([l.strip() for l in open(ag.g, 'r').readlines()])
    srclist, genlist = mangleBazel(srclist), mangleBazel(genlist)

    # Instantiate ninja writer
    cursor = Writer(open(ag.o, 'w'))
    ninjaCommonHeader(cursor, ag)

    # generate .pb.cc and .pb.h
    _, srclist = eGrep('.*.proto$', srclist)
    protolist, genlist = eGrep('.*.pb.cc', genlist)
    _, genlist = eGrep('.*.pb.h', genlist)
    protolist = [re.sub('.pb.cc', '.proto', x) for x in protolist]
    ninjaProto(cursor, protolist)

    # generate .pb_text.cc .pb_text.h .pb_test-impl.h
    _, srclist = eGrep('.*.proto$', srclist)
    protolist, genlist = eGrep('.*.pb_text.cc', genlist)
    _, genlist = eGrep('.*.pb_text.h', genlist)
    _, genlist = eGrep('.*.pb_text-impl.h', genlist)
    protolist = [re.sub('.pb_text.cc$', '.proto', x) for x in protolist]
    ninjaProtoText(cursor, protolist)

    # generate version info, the last bit in list of generated files
    print('Unprocessed generated files:', genlist)
    assert(len(genlist) == 1)
    srclist.extend(cursor.build(genlist[0], 'GEN_VERSION_INFO'))

    # ignore .h files and third_party, and windows source
    _, srclist = eGrep('.*.h$', srclist)
    _, srclist = eGrep('^third_party', srclist)
    _, srclist = eGrep('.*windows/env_time.cc$', srclist)
    _, srclist = eGrep('.*platform/windows.*', srclist)
    _, srclist = eGrep('.*stream_executor.*', srclist) # due to CPU-only

    # compile .cc source
    cclist, srclist = eGrep('.*.cc', srclist)
    tf_android_objs = ninjaCXXOBJ(cursor, cclist)

    # link the final executable
    cursor.build('libtensorflow_android.so', 'CXX_SHLIB', inputs=tf_android_objs)

    ## fflush
    cursor.close()
    print('Unprocessed source files:', srclist)


if __name__ == '__main__':

    # A graceful argparse implementation with argparse subparser requries
    # much more boring code than I would like to write.
    try:
        sys.argv[1]
    except IndexError as e:
        print(e, 'you must specify one of the following a subcommand:')
        print([k for (k, v) in locals().items() if k.startswith('shogun')])
        exit(1)

    # Targets sorted in dependency order.
    if sys.argv[1] == 'ProtoText':
        shogunProtoText(sys.argv[2:])
    elif sys.argv[1] == 'TFCoreProto':
        shogunTFCoreProto(sys.argv[2:])
    elif sys.argv[1] == 'TFFrame':
        shogunTFFrame(sys.argv[2:])
    elif sys.argv[1] == 'TFLibAndroid':
        shogunTFLibAndroid(sys.argv[2:])
    else:
        raise NotImplementedError(sys.argv[1:])
