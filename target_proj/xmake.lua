set_toolchains('gcc')

add_cxflags('-g3', '-O0')

target('main')
    set_kind('binary')
    add_files('**.c')
